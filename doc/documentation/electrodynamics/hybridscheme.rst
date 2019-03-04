.. _hybridscheme:

===============================
Hybrid Quantum/Classical Scheme
===============================

The basic idea is to separate the calculation into two parts:
the first one is the quantum subsystem, which is propagated
using :ref:`timepropagation` scheme, and the second one is
the classical subsystem that is treated using :ref:`qsfdtd`.
The subsystems are propagated separately in their own
real space grids, but they share a common electrostatic potential.

In the :ref:`timepropagation` part of the calculation the electrostatic
potential is known as the Hartree potential `V^{\rm{qm}}(\mathbf{r}, t)`
and it is solved from the Poisson equation
`\nabla^2 V^{\rm{qm}}(\mathbf{r}, t) = -4\pi\rho^{\rm{qm}}(\mathbf{r}, t)`

In the :ref:`qsfdtd` the electrostatic potential is solved from
the Poisson equation as well:
`V^{\rm{cl}}(\mathbf{r}, t) = -4\pi\rho^{\rm{cl}}(\mathbf{r}, t).`

The hybrid scheme is created by replacing in both schemes the
electrostatic (Hartree) potential by a common potential:
`\nabla^2 V^{\rm{tot}}(\mathbf{r}, t) = -4\pi\left[\rho^{\rm{cl}}(\mathbf{r}, t)+\rho^{\rm{qm}}(\mathbf{r}, t)\right].`

-----------
Double grid
-----------
The observables of the quantum and classical subsystems are
defined in their own grids, which are overlapping but can
have different spacings. The following restrictions must hold:

* The quantum grid must fit completely inside the classical grid
* The spacing of the classical grid `h_{\rm{cl}}` must
  be equal to `2^n h_{\rm{qm}}`, where `h_{\rm{qm}}`
  is the spacing of the quantum grid and n is an integer.

When these conditions hold, the potential from one subsystem can
be transferred to the other one. The grids are automatically
adjusted so that some grid points are common.

--------------------------------------------
Transferring the potential between two grids
--------------------------------------------
* Transferring the potential from classical subsystem to the quantum
  grid is performed by interpolating the classical potential to the
  denser grid of the quantum subsystem. The interpolation only takes
  place in the small subgrid around the quantum mechanical region.
* Transferring the potential from quantum subsystem to the classical
  one is done in another way: instead of the potential itself, it is
  the quantum mechanical electron density
  `\rho^{\rm{qm}}(\mathbf{r}, t)` that is copied to the
  coarser classical grid. Its contribution to the total electrostatic
  potential is then determined by solving the Poisson equation in that grid.
* Altogether this means that although there is only one potential to be
  determined `(V^{\rm{tot}}(\mathbf{r}, t))`, three Poisson equations
  must be solved:

  1. `V^{\rm{cl}}(\mathbf{r}, t)` in classical grid
  2. `V^{\rm{qm}}(\mathbf{r}, t)` in quantum grid
  3. `V^{\rm{qm}}(\mathbf{r}, t)` in classical grid

  When these are ready and `V^{\rm{cl}}(\mathbf{r}, t)` is transferred
  to the quantum grid, `V^{\rm{tot}}(\mathbf{r}, t)` is determined
  in both grids. 

----------------------------------------------------------------------------
Example: photoabsorption of Na2 near gold nanosphere
----------------------------------------------------------------------------
This example calculates the photoabsorption of `\text{Na}_2` molecule
in (i) presence and (ii) absence of a gold nanosphere:

.. literalinclude:: gold+na2_nanosphere/calculate.py

|enhanced_absorption|

.. |enhanced_absorption| image:: gold+na2_nanosphere/hybrid.png

The optical response of the molecule apparently enhances when
it is located near the metallic nanoparticle, see Ref. \ [#Sakko]_ for
more examples. The geometry and the distribution
of the grid points are shown in the following figure
(generated with :download:`this script <gold+na2_nanosphere/plot_geom.py>`):

|geometry|

.. |geometry| image:: gold+na2_nanosphere/geom.png


.. _hybrid-inducedfield:

----------------------------------------------------------------------------
Advanced example: Near field enhancement of hybrid system
----------------------------------------------------------------------------
In this example we calculate the same hybrid Na2 + gold nanoparticle
system as above, but using the advanced syntax instead of the
:code:`QSFDTD` wrapper. This allows us to include :code:`InducedField` observers
in the calculation, see
:ref:`TDDFTInducedField module documentation <inducedfield_timepropagation>`:

.. literalinclude:: gold+na2_nanosphere_inducedfield/calculate.py

The :code:`TDDFTInducedField` records the quantum part of the calculation and
the :code:`FDTDInducedField` records the classical part.
We can calculate the individual and the total induced field
by the following script:

.. literalinclude:: gold+na2_nanosphere_inducedfield/postprocess.py

All the :code:`InducedField` objects
can be analyzed in the same way as described in
:ref:`TDDFTInducedField module documentation <inducedfield_timepropagation>`.
Here we show an example script
for plotting (run in serial mode, i.e., with one process):

.. literalinclude:: gold+na2_nanosphere_inducedfield/plot.py

This produces the following figures for the electric near field:

|cl_fe| |qm_fe| |tot_fe|

.. |cl_fe| image:: gold+na2_nanosphere_inducedfield/cl_field.ind_Ffe.png
   :scale: 70 %
.. |qm_fe| image:: gold+na2_nanosphere_inducedfield/qm_field.ind_Ffe.png
   :scale: 70 %
.. |tot_fe| image:: gold+na2_nanosphere_inducedfield/tot_field.ind_Ffe.png
   :scale: 70 %


----------
References
----------

.. [#Sakko] A. Sakko, T. P. Rossi and R. M. Nieminen,
            Dynamical coupling of plasmons and molecular excitations by hybrid quantum/classical calculations: time-domain approach
            *J. Phys.: Condens. Matter* **26**, 315013 (2014)
