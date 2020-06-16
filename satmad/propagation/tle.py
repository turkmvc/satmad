# SatMAD: Satellite Mission Analysis and Design for Python
#
# Copyright (C) 2020 Egemen Imre
#
# Licensed under GNU GPL v3.0. See LICENSE.rst for more info.
"""
Two-Line-Elements to represent satellites in Earth orbit.

"""
import numpy as np
from astropy import units as u
from astropy.time import Time
from astropy.units import Quantity
from sgp4.earth_gravity import wgs72
from sgp4.exporter import export_tle
from sgp4.model import WGS72, Satrec

# precompile the unit as constant
_DAY_TO_SEC = (1.0 * u.day).to(u.s)


class TLE:
    """
    A two-line element set (TLE) is a data format encoding a list of TEME
    (True Equator, Mean Equinox) mean orbital elements
    of an Earth-orbiting object for a given point in time, called the Epoch Time.

    These orbital elements are solely for use with the SGP4 propagator due to the
    analytical orbit theory used in its derivation.

    See the `TLE page in Wikipedia <https://en.wikipedia.org/wiki/Two-line_element_set>`_
    or `NASA definition <https://spaceflight.nasa.gov/realdata/sightings/SSapplications/Post/JavaSSOP/SSOP_Help/tle_def.html>`_
    for more information.

    The TLEs are usually generated by external sources and are used to propagate
    the orbits with the initial condition encapsulated by the TLE.

    Parameters
    ----------
    epoch : Time
        Epoch Time corresponding to the orbital elements (nominally very near
        the time of true ascending node passage)
    inclination : float or Quantity
        TEME mean inclination of the orbit [rad]
    raan : float or Quantity
        TEME mean right ascension of ascending node (RAAN) of the orbit [rad]
    eccentricity : float
        mean eccentricity of the orbit
    arg_perigee : float or Quantity
        TEME mean argument of perigee [rad]
    mean_anomaly : float or Quantity
        mean anomaly of the orbit [rad]
    mean_motion : float
        mean motion of the orbit [rad/sec]
    bstar : float or Quantity
        sgp4 type drag coefficient [1 / earth radius] (see TLE class documentation)
    n_dot : float or Quantity
        First time derivative of the mean motion or
        Ballistic Coefficient [revs/day] (see TLE class documentation)
    n_dotdot : float or Quantity
        Second time derivative of the mean motion (see TLE class documentation)
    name : str
        Common name of the satellite
    intl_designator : str
        international designator on card 1 (up to 8 characters) (see class definition)
    sat_num : int
        satellite catalog number (see TLE class documentation)
    classification : str
        Classification (`U` for Unclassified, `C` for Classified, `S` for Secret)
    rev_nr : int
        Revolution number of the object at Epoch Time [revolutions]
    el_nr : int
        Element set number. Incremented when a new TLE is generated for this object.
    """

    # Gravitational constants(defaults to WGS72)
    _grav_model = WGS72
    _mu = wgs72.mu * (u.km ** 3 / u.s ** 2)  # in km3 / s2
    _earth_radius = wgs72.radiusearthkm * u.km  # km
    _j2 = wgs72.j2

    # Hardcoded defaults
    _ops_mode = "i"

    def __init__(
        self,
        epoch,
        inclination,
        raan,
        eccentricity,
        arg_perigee,
        mean_anomaly,
        mean_motion,
        bstar,
        n_dot,
        n_dotdot=0.0,
        name="NONAME",
        intl_designator="12345A",
        sat_num=99999,
        classification="U",
        rev_nr=0,
        el_nr=1,
    ):
        # init internal satrec object
        self._satrec: Satrec = Satrec()

        # recreate the epoch composite
        yydd_str = epoch.utc.to_value("yday", subfmt="date").split(":")
        self._satrec.epochyr = int(yydd_str[0][-2:])
        self._satrec.epochdays = int(yydd_str[1]) + epoch.mjd % 1
        epoch_yydd = self._satrec.epochyr * 1000 + self._satrec.epochdays

        # check inclination range
        inclination_val = _force_angles_to_rad(inclination)
        if not 0 <= inclination_val < np.pi:
            raise ValueError(
                f"Given argument ({inclination}) is an invalid "
                f"Inclination value, "
                f"only values in range 0 <= i < PI are allowed."
            )

        # fill the Satrec object
        self._satrec.sgp4init(
            TLE._grav_model,
            TLE._ops_mode,
            sat_num,
            epoch_yydd,
            bstar,
            n_dot,
            n_dotdot,
            eccentricity,
            _force_angle_range(arg_perigee),
            inclination_val,
            _force_angle_range(mean_anomaly),
            mean_motion * 60,  # convert to seconds
            _force_angle_range(raan),
        )

        # fill time with precise Time information
        self._epoch = epoch.utc.replicate(format="isot")
        self._satrec.jdsatepoch = self._epoch.jd1
        self._satrec.jdsatepochF = self._epoch.jd2

        # load other TLE info
        self._satrec.classification = classification
        self._satrec.intldesg = intl_designator
        self._satrec.revnum = rev_nr
        self._satrec.ephtype = "0"  # always 0 in distributed ephemeris
        self._satrec.elnum = el_nr

        # load TLE name
        self._name = name

    @classmethod
    def from_tle(
        cls, line1, line2, name="No Name",
    ):
        """
        Initialises the TLE from two strings.

        Parameters
        ----------
        line1 : str
            First line of the TLE
        line2 : str
            Second line of the TLE
        name : str
            Name of the object / satellite

        Returns
        -------
        TLE
            `TLE` object initialised with the two line input.
        """
        # create object without calling `__init__`
        tle = cls.__new__(cls)

        # init Satrec object with TLE strings
        tle._satrec = Satrec.twoline2rv(line1, line2, whichconst=TLE._grav_model)

        # Fill epoch in Time
        tle._epoch = Time(
            tle._satrec.jdsatepoch, tle._satrec.jdsatepochF, scale="utc", format="jd"
        )

        # load TLE name
        tle._name = name

        return tle

    @classmethod
    def init_geo(
        cls,
        epoch,
        longitude,
        name="No Name",
        intl_designator="12345A",
        sat_num=99999,
        classification="U",
        rev_nr=0,
        el_nr=1,
    ):
        """
        Initialises a geostationary satellite TLE.
        Due to the nature of the Earth's geopotential, the orbit may drift off
        by some degrees within weeks.

        Parameters
        ----------
        epoch : Time
            Epoch Time corresponding to the orbital elements (nominally very near
            the time of true ascending node passage)
        longitude : float or Quantity
            initial longitude of the satellite
        name : str
            Common name of the satellite
        intl_designator : str
            international designator on card 1 (up to 8 characters) (see class definition)
        sat_num : int
            satellite catalog number (see TLE class documentation)
        classification : str
            Classification (`U` for Unclassified, `C` for Classified, `S` for Secret)
        rev_nr : int
            Revolution number of the object at Epoch Time [revolutions]
        el_nr : int
            Element set number. Incremented when a new TLE is generated for this object.

        Returns
        -------
          TLE
                `TLE` object initialised with the required GEO parameters.
        """
        # init GEO specific values - period is one sidereal day
        mean_motion = 2 * np.pi / (1.0 * u.sday).to_value(u.s)
        raan = epoch.sidereal_time("mean", longitude)

        bstar = 0  # no drag
        n_dot = 0  # mean motion assumed constant

        # init standard (near) circular orbit
        inclination = 0.0 * u.deg
        eccentricity = 1e-9  # cannot be zero
        arg_perigee = 0.0 * u.deg
        mean_anomaly = 0.0 * u.deg

        tle = TLE(
            epoch,
            inclination,
            raan,
            eccentricity,
            arg_perigee,
            mean_anomaly,
            mean_motion,
            bstar,
            n_dot,
            n_dotdot=0.0,
            name=name,
            intl_designator=intl_designator,
            sat_num=sat_num,
            classification=classification,
            rev_nr=rev_nr,
            el_nr=el_nr,
        )

        return tle

    def __str__(self):
        """
        Exports the TLE as a Three-Line string, with name, line1 and line2.

        A sample output looks like this::

            ISS (ZARYA)
            1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927
            2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537

        Returns
        -------
        str
            string containing line 1, line 2 and name of the satellite
        """
        line1, line2 = export_tle(self._satrec)

        txt = ""
        if self._name is not None and self._name.strip():
            txt += self._name + "\n"

        txt += line1 + "\n" + line2 + "\n"

        return txt

    def period(self) -> Quantity:
        """Computes the satellite period [sec]."""
        return 2 * np.pi / self.mean_motion * u.s

    def sm_axis(self) -> Quantity:
        """Computes the semimajor axis [km].

        Note that the :math:`mu` value used in the computation of the semimajor axis
        is that of WGS72 for consistency with the orbital elements definition.
        """
        n = self.mean_motion
        return np.power(TLE._mu.value / n / n, 1 / 3) * u.km

    def node_rotation_rate(self):
        """
        Node (or orbital plane) rotation rate due to J2.

        Note that, WGS72 constants for J2 and Earth Radius (R_E) are used in
        the computation for consistency with the orbital elements definition.

        Returns
        -------
        Quantity
            Node rotation rate (deg/day)
        """
        n = self.mean_motion
        r_e = TLE._earth_radius
        e = self.eccentricity
        p = self.sm_axis() * (1 - e * e)
        j2 = TLE._j2
        i = self.inclination

        node_rot = (-3 * n * r_e * r_e * j2 / (2 * p * p) * np.cos(i)) * (u.rad / u.s)

        return node_rot.to(u.deg / u.day)

    def argp_rotation_rate(self):
        """
        Argument of Perigee (or eccentricity vector) rotation rate due to J2.

        Note that, WGS72 constants for J2 and Earth Radius (R_E) are used in
        the computation for consistency with the orbital elements definition.

        Returns
        -------
        Quantity
            Arg of Perigee rotation rate (deg/day)
        """
        n = self.mean_motion
        r_e = TLE._earth_radius
        e = self.eccentricity
        p = self.sm_axis() * (1 - e * e)
        j2 = TLE._j2
        sin_i = np.sin(self.inclination)

        argp_rot = (
            3.0
            * n
            * r_e
            * r_e
            * j2
            / (4.0 * p * p)
            * (4.0 - 5.0 * sin_i * sin_i)
            * (u.rad / u.s)
        )

        return argp_rot.to(u.deg / u.day)

    @property
    def epoch(self) -> Time:
        """Returns the epoch time associated with the orbital parameters."""
        return self._epoch

    @property
    def bstar(self) -> float:
        """Returns the sgp4 type drag coefficient [1 / earth radius]."""
        return self._satrec.bstar

    @property
    def n_dot(self) -> float:
        """
        Gets and sets the first time derivative of the mean motion or
        Ballistic Coefficient [revs/day].

        Absolute value of the first time derivative of the mean motion
        can only be less than 1.0 (exclusive). Raises a `ValueError` otherwise.
        """
        return self._satrec.ndot

    @n_dot.setter
    def n_dot(self, n_dot):
        if abs(n_dot) < 1.0:
            self._satrec.ndot = n_dot
        else:
            raise ValueError(
                f"Given argument ({n_dot}) is an invalid derivative of mean motion, "
                f"only absolute values less than 1.0 (exclusive) are allowed."
            )

    @property
    def n_dotdot(self) -> float:
        """Returns the Second time derivative of the mean motion."""
        return self._satrec.nddot

    @property
    def inclination(self) -> Quantity:
        """Gets and sets the TEME mean inclination of the orbit [rad].

        Inclination should be in range 0 <= om < PI.
        Raises a `ValueError` otherwise.
        """
        return self._satrec.inclo * u.rad

    @inclination.setter
    def inclination(self, i):
        """
        Parameters
        ----------
        i : float or Quantity
        """
        i_val = _force_angles_to_rad(i)

        if 0 <= i_val < np.pi:
            self._satrec.inclo = i_val
        else:
            raise ValueError(
                f"Given argument ({i}) is an invalid "
                f"Inclination value, "
                f"only values in range 0 <= i < PI are allowed."
            )

    @property
    def raan(self) -> Quantity:
        """Gets and sets the TEME mean right ascension of ascending node (RAAN)
        of the orbit [rad].

        RAAN should be in range 0 <= om < 2*PI.
        Raises a `ValueError` otherwise."""
        return self._satrec.nodeo * u.rad

    @raan.setter
    def raan(self, om):
        """
        Parameters
        ----------
        om : float or Quantity
        """
        om_val = _force_angle_range(om)

        if 0 <= om_val < 2 * np.pi:
            self._satrec.nodeo = om_val
        else:
            raise ValueError(
                f"Given argument ({om}) is an invalid "
                f"RAAN value, "
                f"only values in range 0 <= om < 2*PI are allowed."
            )

    @property
    def eccentricity(self) -> float:
        """Gets and sets the mean eccentricity of the orbit.

        Eccentricity should be in range 0 <= e < 1.0.
        Raises a `ValueError` otherwise."""
        return self._satrec.ecco

    @eccentricity.setter
    def eccentricity(self, e):
        if 0 <= e < 1.0:
            self._satrec.ecco = e
        else:
            raise ValueError(
                f"Given argument ({e}) is an invalid "
                f"Eccentricity value, "
                f"only values in range 0 <= e < 1.0 are allowed."
            )

    @property
    def arg_perigee(self) -> Quantity:
        """Gets and sets the TEME mean argument of perigee [rad].

        Argument of perigee should be in range 0 <= argp < 2*PI.
        Raises a `ValueError` otherwise.
        """
        return self._satrec.argpo * u.rad

    @arg_perigee.setter
    def arg_perigee(self, argp):
        """
        Parameters
        ----------
        argp : float or Quantity
        """
        argp_val = _force_angle_range(argp)

        if 0 <= argp_val < 2 * np.pi:
            self._satrec.argpo = argp_val
        else:
            raise ValueError(
                f"Given argument ({argp}) is an invalid "
                f"Argument of Perigee value, "
                f"only values in range 0 <= om < 2*PI are allowed."
            )

    @property
    def mean_anomaly(self) -> Quantity:
        """Gets and sets the mean anomaly of the orbit [rad].

        Mean Anomaly should be in range 0 <= m_anom < 2*PI.
        Raises a `ValueError` otherwise.
        """
        return self._satrec.mo * u.rad

    @mean_anomaly.setter
    def mean_anomaly(self, m_anom):
        """
        Parameters
        ----------
        m_anom : float or Quantity
        """
        m_anom_val = _force_angles_to_rad(m_anom)
        if 0 <= m_anom_val < 2 * np.pi:
            self._satrec.mo = m_anom_val
        else:
            raise ValueError(
                f"Given argument ({m_anom}) is an invalid "
                f"Mean Anomaly value, "
                f"only values in range 0 <= m_anom < 2*PI are allowed."
            )

    @property
    def mean_motion(self) -> float:
        """Gets and sets the mean motion of the orbit [rad/sec].

        Mean Motion in revs/day should be in range 0 < n <= 17.0.
        Raises a `ValueError` otherwise.
        """
        return self._satrec.no_kozai / 60.0

    @mean_motion.setter
    def mean_motion(self, n: float):
        no = _DAY_TO_SEC.to_value() * n / (2 * np.pi)
        if 0 < no <= 17.0:
            self._satrec.no_kozai = n * 60
        else:
            raise ValueError(
                f"Given argument ({n}, converted to {no}) is an invalid "
                f"Mean Motion value, "
                f"only values in range 0 < n <= 17.0 are allowed."
            )

    @property
    def name(self) -> str:
        """Gets and sets the common name of the satellite.

        Satellite name cannot be `None` or empty, "NO NAME" is then assigned
        automatically.
        """
        return self._name

    @name.setter
    def name(self, name):
        if name is None or not name:
            self._name = "NO NAME"
        else:
            self._name = name

    @property
    def sat_number(self) -> int:
        """Returns the satellite catalog number."""
        return self._satrec.satnum

    @property
    def intl_designator(self) -> str:
        """
        Gets or sets the international designator of the satellite.

        International Designator can only be between 0 and 100000
        (exclusive at both ends). Raises a `ValueError` otherwise.
        """
        return self._satrec.intldesg

    @intl_designator.setter
    def intl_designator(self, intl_designator):
        self._satrec.intldesg = intl_designator

    @property
    def classification(self) -> str:
        """
        Gets or sets the classification of the satellite.

        Classification type can only be `U`, `C` or `S`. Raises a `ValueError`
        otherwise.
        """
        return self._satrec.classification

    @classification.setter
    def classification(self, sec_class):
        if sec_class == "U" or sec_class == "C" or sec_class == "S":
            self._satrec.classification = sec_class
        else:
            raise ValueError(
                f"Given argument ({sec_class}) is an invalid classification type, "
                f"only U, C, S are allowed."
            )

    @property
    def rev_nr(self) -> int:
        """
        Gets or sets the Revolution Number of the object at Epoch Time [revolutions].

        Revolution Number can only be between 0 and 100000
        (exclusive at both ends). Raises a `ValueError` otherwise.
        """
        return self._satrec.revnum

    @rev_nr.setter
    def rev_nr(self, rev_nr):
        if 0 < rev_nr < 100000:
            self._satrec.revnum = rev_nr
        else:
            raise ValueError(
                f"Given argument ({rev_nr}) is an invalid Revolution Number, "
                f"only values between 0 and 100000 (exclusive) are allowed."
            )

    @property
    def el_nr(self) -> int:
        """Gets and sets the Element set number.

        Incremented when a new TLE is generated for this object.

        Element set number should be in range 0 <= el_nr < 10000.
        Raises a `ValueError` otherwise.
        """
        return self._satrec.elnum

    @el_nr.setter
    def el_nr(self, el_nr):
        if 0 <= el_nr < 10000:
            self._satrec.elnum = el_nr
        else:
            raise ValueError(
                f"Given argument ({el_nr}) is an invalid Element Set Number, "
                f"only values between 0 and 10000 (exclusive) are allowed."
            )


def _force_angles_to_rad(angle):
    """
    Forces a `Quantity` or a float to output float in radians.

    Parameters
    ----------
    angle : float or Quantity

    Returns
    -------
    float
        The angle in radians
    """
    if isinstance(angle, Quantity):
        angle_rad = angle.to_value(u.rad)
    else:
        angle_rad = angle

    return angle_rad


def _force_angle_range(angle_rad, min_range=0, max_range=2 * np.pi):
    """
    Forces the angles into a prescribed range.

    Parameters
    ----------
    angle_rad : float or Quantity
        Angle in radians
    min_range : float
        Minimum value allowable
    max_range : float
        Max value allowable

    Returns
    -------
    float
        Angle value forced into the required range
    """

    angle = _force_angles_to_rad(angle_rad)

    if max_range < angle:
        angle = angle - 2 * np.pi

    if angle_rad < min_range:
        angle = angle + 2 * np.pi

    return angle
