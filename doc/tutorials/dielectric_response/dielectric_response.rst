.. _df_tutorial:

================================================
Linear dielectric response of an extended system
================================================

A short introduction
=====================

The DielectricFunction object can calculate the dielectric function of an
extended system from its ground state electronic structure. The frequency and
wave-vector dependent linear dielectric matrix in reciprocal space
representation is written as

.. math:: \epsilon_{\mathbf{G} \mathbf{G}^{\prime}}(\mathbf{q}, \omega)

where `\mathbf{q}` and  `\omega` are the momentum and energy
transfer in an excitation, and `\mathbf{G}` is reciprocal lattice
vector. The off-diagonal element of
`\epsilon_{\mathbf{G} \mathbf{G}^{\prime}}` determines the local field
effect.

The macroscopic dielectric function is defined by (with local field correction)

.. math:: \epsilon_{M}(\mathbf{q},\omega) =
              \frac{1}{\epsilon^{-1}_{00}(\mathbf{q},\omega)}

Ignoring the local field (the off-diagonal element of dielectric matrix)
results in:

.. math::  \epsilon_{M}(\mathbf{q},\omega) = \epsilon_{00}(\mathbf{q},\omega)

Optical absorption spectrum is obtained through

.. math:: \mathrm{ABS} = \mathrm{Im}
              \epsilon_{M}(\mathbf{q} \rightarrow 0,\omega)

Electron energy loss spectrum (EELS) is get by

.. math:: \mathrm{EELS} = -\mathrm{Im}
              \frac{1}{\epsilon_{M}(\mathbf{q},\omega)}

The macroscopic dielectric function is ill defined for systems of
reduced dimensionality. In these cases `\epsilon_M = 1.0`. The
polarizability will maintain its structure for lower dimensionalities
and is in 3D related to the macroscopic dielectric function as,

.. math:: \mathrm{Im} \epsilon_{M}(\mathbf{q},\omega) =
              4 \, \pi \, \mathrm{Im} \alpha_M(\mathbf{q},\omega)

Refer to :ref:`df_theory`  for detailed documentation on theoretical part.

.. _df_tutorial_freq:

Frequency grid
==============

The dielectric function is evaluted on a non-linear frequency grid according
to the formula

.. math::

    \omega_i = i \frac{\Delta\omega_0}
    {1 -(\sqrt2 - 1)\frac{\Delta\omega_0}{\omega_2} i},
    i = 0, 1, ...,

The parameter `\Delta\omega_0` is the frequency spacing at `\omega=0` and
`\omega_2` is the frequency where the spacing has increased to
`2\Delta\omega_0`. In general a lower value of `\omega_2` gives a more non-
linear grid and less frequency points.

Below, the frequency grid is visualized for different values of
`\omega_2`. You can find the script for reproducing this figure here:
:download:`plot_freq.py`.

.. image:: nl_freq_grid.png
    :align: center

The parameters can be specified using keyword arguments::

    df = DielectricFunction(...,
                            domega0=0.05,   # eV. Default = 0.1
                            omega2=5.0,     # Default = 10.0
                            omegamax=15.0)  # eV. Default is the maximum
                                            #  difference between energy
                                            #  eigenvalues

Setting ``omegamax`` manually is usually not advisable, however you
might want it in cases where semi-core states  are included where very large
energy eigenvalue differences appear.


Example 1: Optical absorption of semiconductor: Bulk silicon
============================================================

A simple startup
----------------

Here is a minimum script to get an absorption spectrum.

.. literalinclude:: silicon_ABS_simpleversion.py

This script takes less than one minute on a single cpu, and generates a file
'df.csv' containing the optical (`\mathbf{q} = 0`) dielectric function
along the x-direction, which is the default direction. The file 'df.csv'
contain five columns ordered as follows: `\omega` (eV),
`\mathrm{Re}(\epsilon_{\mathrm{NLF}})`,
`\mathrm{Im}(\epsilon_{\mathrm{NLF}})`,
`\mathrm{Re}(\epsilon_{\mathrm{LF}})`,
`\mathrm{Im}(\epsilon_{\mathrm{LF}})` where
`\epsilon_{\mathrm{NLF}}` and `\epsilon_{\mathrm{LF}}` is the
result without and with local field effects, respectively.

For other directions you can specify the direction and filename like::

 DielectricFunction.get_dielectric_function(...,
                                            direction='y',
                                            filename='filename.csv',
                                            ...)

The absorption spectrum along the x-direction including local field effects
can then be plotted using

.. literalinclude:: plot_silicon_ABS_simple.py

The resulting figure is shown below. Note that there is significant
absorption close to `\omega=0` because of the large default
Fermi-smearing in GPAW. This will be dealt with in the following more realistic
calculation.

.. image:: si_abs.png
    :align: center


More realistic calculation
--------------------------

To get a realistic silicon absorption spectrum and macroscopic dielectric
constant, one needs to converge the calculations with respect to grid
spacing, kpoints, number of bands, planewave cutoff energy and so on. Here
is an example script: :download:`silicon_ABS.py`. In the following, the script
is split into different parts for illustration.

1. Ground state calculation

  .. literalinclude:: silicon_ABS.py
      :lines: 1-29

  In this script a normal ground state calculation is performed with coarse
  kpoint grid. The calculation is then restarted with a fixed density and the
  full hamiltonian is diagonalized exactly on a densely sampled kpoint grid.
  This is the preferred procedure of obtained the excited KS-states because it
  is in general difficult to converge the excited states using iterative
  solvers. A full diagonalization is more robust.

  .. note::

    For semiconductors, it is better to use either small Fermi-smearing in the
    ground state calculation::

      from gpaw import FermiDirac
      calc = GPAW(...
                  occupations=FermiDirac(0.001),
                  ...)

    or larger ftol, which determines the threshold for transition
    in the dielectric function calculation (`f_i - f_j > ftol`), not
    shown in the example script)::

       df = DielectricFunction(...
                               ftol=1e-2,
                               ...)

2. Get absorption spectrum

  .. literalinclude:: silicon_ABS.py
      :lines: 31-36

  Here ``eta`` is the broadening parameter of the calculation, and ``ecut``
  is the local field effect cutoff included in the dielectric function.

3. Get macroscopic dielectric constant

  The macroscopic dielectric constant is defined as the real part of dielectric
  function at `\omega=0`.   In the following script, only a single
  point at `\omega=0` is calculated without using the hilbert transform
  (which is only compatible with the non-linear frequency grid specification).

  .. literalinclude:: silicon_ABS.py
      :lines: 38-
      :language: python

  In general, local field correction will reduce this value by 10-20%.


Result
------

The figure shown here is generated from script :
:download:`silicon_ABS.py` and :download:`plot_ABS.py`.
It takes 30 minutes with 16 cpus on Intel Xeon X5570 2.93GHz.

.. image:: silicon_ABS.png
    :height: 300 px
    :align: center

The arrows are data extracted from \ [#Kresse]_.

The calculated macroscopic dielectric constant can be seen in the table below
and compare good with the values from [#Kresse]_. The experimental value is
11.90. The larger theoretical value results from the fact that the ground
state LDA (even GGA) calculation underestimates the bandgap.

.. csv-table::
   :file: mac_eps.csv


Example 2: Electron energy loss spectra
=======================================

Electron energy loss spectra (EELS) can be used to explore the plasmonic
(collective electronic) excitations of an extended system. This is because
the energy loss of a fast electron passing by a material is defined by

.. math:: \mathrm{EELS} = -\mathrm{Im} \frac{1}{\epsilon(\mathbf{q}, \omega)}

and the plasmon frequency `\omega_p` is defined as when
`\epsilon(\omega_p) \rightarrow 0`. It means that an external
perturbation at this frequency, even infinitesimal, can generate large
collective electronic response.

A simple startup: bulk aluminum
-------------------------------

Here is a minimum script to get an EELS spectrum.

.. literalinclude:: aluminum_EELS.py

This script takes less than one minute on a single cpu and by default,
generates a file 'EELS.csv'. Then you can plot the file using

.. literalinclude:: plot_aluminum_EELS_simple.py

The three columns of this file correspond to energy (eV), EELS without and
with local field correction, respectively. You will see a 15.9 eV peak.
It comes from the bulk plasmon excitation of aluminum. You can explore the
plasmon dispersion relation  `\omega_p(\mathbf{q})` by
tuning `\mathbf{q}` in the calculation above.

.. image:: aluminum_EELS.png
    :height: 300 px
    :align: center

.. Note::

    The momentum transfer `\mathbf{q}` in an EELS calculation must be
    the difference between two kpoints! For example, if you have an
    kpts=(Nk1, Nk2, Nk3) Monkhorst-Pack k-sampling in the ground state
    calculation, you have to choose
    `\mathbf{q} = \mathrm{np.array}([i/Nk1, j/Nk2, k/Nk3])`, where
    `i, j, k` are integers.


A more sophisticated example: graphite
--------------------------------------

Here is a more sophisticated example of calculating EELS of graphite with
different  `\mathbf{q}`.  You can also get the script here:
:git:`~doc/tutorials/dielectric_response/graphite_EELS.py`. The results
(plot) are shown in the following section.

.. literalinclude:: graphite_EELS.py


Results on graphite
-------------------

The figure shown here is generated from script: :download:`graphite_EELS.py`
and :download:`plot_EELS.py`

.. image:: graphite_EELS.png
           :height: 500 px

One can compare the results with literature  \ [#Rubio]_.


.. _tetrahedron:

Example 3: Tetrahedron integration (experimental)
=================================================

The k-point integral needed for the calculation of the density response
function, is typically performed using a simple summation of individual
k-points. By setting the integration mode to 'tetrahedron integration' the
kpoint integral is calculated by interpolating density matrix elements and
eigenvalues. This typically means that fewer k-points are needed for
convergence.

The combination of using the tetrahedron method and reducing the kpoint
integral using crystal symmetries means that it is necessary to be careful
with the kpoint sampling which should span the whole irreducible zone.
Luckily, :git:`~gpaw/bztools.py` provides the tool to generate such an
k-point sampling autimatically::

    from gpaw.bztools import find_high_symmetry_monkhorst_pack
    kpts = find_high_symmetry_monkhorst_pack(
        'gs.gpw',  # Path to ground state .gpw file
        density=20.0)  # The required minimum density

If the system is lower dimensional this function takes an optional argument
``pbc`` a tuple of bools which for slab with a non-periodic z direction is
given by ``pbc=[True, True, False]``. If combined with the tetrahedron method
it is necessary to tell the ``DielectricFunction`` object which directions
are non-periodic. The recipe for non-periodic systems is given below::

    from gpaw.bztools import find_high_symmetry_monkhorst_pack
    from gpaw.response.df import DielectricFunction
    pbc = [True, True, False]
    kpts = find_high_symmetry_monkhorst_pack(
        'gs.gpw',  # Path to ground state .gpw file
        density=20.0,  # The required minimum density
        pbc=pbc)  # Periodic directions

    df = DielectricFunction(...,
                            integrationmode='tetrahedron integration',
                            pbc=pbc,
                            ...)

Bulk TaS\ :sub:`2`
------------------

As an example, lets calculate the optical properties of a well-known layered
material, namely, the transition metal dichalcogenide (TMD) 2H-TaS\ :sub:`2`\
. We set the structure and find the ground state density with (find the full
script here :download:`tas2_dielectric_function.py`, takes about 10 mins on 8
cores.)

.. literalinclude:: tas2_dielectric_function.py
   :end-before: Unoccupied

The next step is to calculate the unoccupied bands

.. literalinclude:: tas2_dielectric_function.py
   :start-after: Unoccupied
   :end-before: Dielectric function

Lets compare the result of the tetrahedron method with the point sampling
method for broadening of ``eta=25 meV``.

.. literalinclude:: tas2_dielectric_function.py
   :start-after: Dielectric function

The result of which is shown below. Comparing the methods shows that the
calculated dielectric function is much more well behaved when calculated
using the tetrahedron method.

.. image:: tas2_eps.png
    :align: center
    :width: 400 px


Graphene
--------

Graphene represents a material which is particularly difficult
to converge with respect to the number of k-points. This
property originates from its semi-metallic nature and vanishing
density of states at the fermi-level which make the calculated
properties sensitive to the k-point distribution in the vicinity
of the Dirac point. Since the macroscopic dielectric function
is not well-defined for two-dimensional systems we will focus
on calculating the dielectric function an artificial structure
of graphite with double the out-of-plane lattice constant. This
should make its properties similar to graphene. It is well known
that graphene has a sheet conductance of
`\sigma_s=\frac{e^2}{4\hbar}` so, if the individual graphite layers
behave as ideal graphene, the optical properties of the structure
should be determined by

.. math:: \varepsilon = 1 + \frac{4 \pi i}{\omega d} \sigma_s

where `d=3.22` Å is the thickness of graphene. Below we show the
calculated dielectic function
(:download:`graphene_dielectric_function.py`) for a minimum
k-point density of 30 Å\ `^{-1}` corresponding to a kpoint sampling of size
``(90, 90, 1)`` and room temperatur broadening ``eta = 25 meV``. It
is clear that the properties are well converged for large frequencies
using the tetrahedron method. For smaller frequencies the tetrahedron
method fares comparably but convergence is tough for frequencies below
0.5 eV where the absorption spectrum goes to zero. This behaviour is
due to the partially occupied Dirac point which sensitively effects the
integrand of the density response function.

.. image:: graphene_eps.png
    :align: center
    :width: 400 px


Notes on the implementation of the tetrahedron method
-----------------------------------------------------

The tetrahedron method is still in an experimental phase which means that
the user should check the results against the results obtained with
point integration. The method is based on the paper of \ [#MacDonald]_ whom
provide analytical expressions for the response function integration with
interpolated eigenvalues and matrix elements.

In other implementations of the tetrahedron integration method, the division
of the BZ into tetrahedras has been performed using a recursive scheme. In
our implementation we use the external library ``scipy.spatial`` which
provide the ``Delaunay()`` class to calculate Delaunay triangulated k-point
grids from the ground state k-point grid. Delaunay triangulated grids do
necessarily give a good division of the Brillouin zone into tetrahedras and
particularly for homogeneously spaced k-point grids (such as a Monkhorst
Pack) grid many ill-defined tetrahedrons may be created. Such tetrahedrons
are however easily filtered away by removing tetrahedrons with very small
volumes.

- Suggested performance enhancement: ``TetrahedronDescriptor(kpts, simplices=None)``
  Factor out the creation of tetrahedras to make it possible to use user-defined
  tetrahedras. Such an object could inherit from the ``Delaunay()`` class.

Additionally, this library provides a k-dimensional tree implementation
``cKDTree()`` which is used to efficiently identify k-points in the Brillouin
zone. For finite `\mathbf{q}` it is still necessary for the kpoint grid to be
uniform. In the optical limit where `\mathbf{q}=0`, however, it is possible
to use non-uniform k-point grids which can aid a faster convergence,
especially for materials such as graphene.

When using the tetrahedron integration method, the plasmafrequency is
calculated at `T=0` where the expression reduces an integral over the Fermi
surface. The interband transitions are calculated using the temperature
of the ground state calculation. The occupation factors are included as
modifications to the matrix elements as
`\sqrt{f_n - f_m} \langle \psi_m|\nabla |\psi_n \rangle`

- Suggested performance enhancement: Take advantage of the analytical dependence
  of the occupation numbers to treat partially occupied bands more accurately.
  This is expected to improve the convergence of the optical properties of
  graphene for low frequencies.

The entirety of the tetrahedron integration code is written in Python except
for the calculation of the algebraic expression for the response function
integration of a single tetrahedron for which the Python overhead is
significant. The algebraic expression are therefore evaluated in C.


Technical details:
==================

There are few points about the implementation that we emphasize:

* The code is parallelized over kpoints and occupied bands. The
  parallelization over occupied bands makes it straight-forward to utilize
  efficient BLAS libraries to sum un-occupied bands.

* The code employs the Hilbert transform in which the spectral function
  for the density-density response function is calculated before calculating
  the the full density response. This speeds up the code significantly for
  calculations with a lot of frequencies.

* The non-linear frequency grid employed in the calculations is motivated
  by the fact that when using the Hilbert transform the real part of the
  dielectric function converges slowly with the upper bound of the frequency
  grid. Refer to :ref:`df_theory` for the details on the Hilbert transform.


Useful tips
===========

Use dry_run option to get an overview of a calculation (especially useful for
heavy calculations!)::

    $ python3 filename.py --gpaw=df-dry-run=8

.. Note ::

    But be careful ! LCAO mode calculation results in unreliable unoccupied
    states above vacuum energy.

It's important to converge the results with respect to::

    nbands,
    nkpt (number of kpoints in gs calc.),
    eta,
    ecut,
    ftol,
    omegamax (the maximum energy, be careful if hilbert transform is used)
    domega0 (the energy spacing, if there is)
    vacuum (if there is)


Parameters
==========

=================  =================  ===================  ================================
keyword            type               default value        description
=================  =================  ===================  ================================
``calc``           ``str``            None                 gpw filename
                                                           (with 'all' option when writing
                                                           the gpw file)
``name``           ``str``            None                 If specified the chi matrix is
                                                           saved to ``chi+qx+qy+qz.pckl``
                                                           where ``qx, qy, qz`` is the
                                                           wave-vector components in
                                                           reduced coordinates.
``frequencies``    ``numpy.ndarray``  None                 Energies for spectrum. If
                                                           left unspecified the frequency
                                                           grid will be non-linear.
                                                           Ex: numpy.linspace(0,20,201)
``domega0``        ``float``          0.1                  `\Delta\omega_0` for
                                                           non-linear frequency grid.
``omega2``         ``float``          10.0 (eV)            `\omega_2` for
                                                           non-linear frequencygrid.
``omegamax``       ``float``          Maximum energy       Maximum frequency.
                                      eigenvalue
                                      difference.
``ecut``           ``float``          10 (eV)              Planewave energy cutoff.
                                                           Determines the size of
                                                           dielectric matrix.
``eta``            ``float``          0.2 (eV)             Broadening parameter.
``ftol``           ``float``          1e-6                 The threshold for transition:
                                                           `f_{ik} - f_{jk} > ftol`
``txt``            ``str``            stdout               Output filename.
``hilbert``        ``bool``           True                 Switch for hilbert transform.
``nbands``         ``int``            nbands from gs calc  Number of bands from gs calc
                                                           to include.
=================  =================  ===================  ================================


Details of the DF object
========================


.. autoclass:: gpaw.response.df.DielectricFunction
   :members: get_dielectric_function, get_macroscopic_dielectric_constant,
             get_polarizability, get_eels_spectrum


.. [#Kresse] M. Gajdoš, K. Hummer, G. Kresse, J. Furthmüller and F. Bechstedt,
              Linear optical properties in the projected-augmented
              wave methodology,
              *Phys. Rev. B* **73**, 045112 (2006).


.. [#Rubio] A. G. Marinopoulos, L. Reining, A. Rubio and V. Olevano,
             Ab initio study of the optical absorption and
             wave-vector-dependent dielectric response of graphite,
             *Phys. Rev. B* **69**, 245419 (2004).


.. [#MacDonald] 1. MacDonald, A. H., Vosko, S. H. & Coleridge, P. T.,
               Extensions of the tetrahedron method for evaluating spectral
               properties of solids. *J. Phys. C Solid State Phys*. **12**,
               2991–3002 (1979).
