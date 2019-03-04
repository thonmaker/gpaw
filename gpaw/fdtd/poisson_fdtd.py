"""Part of the module for electrodynamic simulations."""

import numpy as np
from ase import Atoms
from ase.io.trajectory import read_atoms
from ase.units import Bohr

import gpaw.mpi as mpi
from gpaw import GPAW
from gpaw.fdtd.polarizable_material import PolarizableMaterial
from gpaw.fdtd.potential_couplers import (RefinerPotentialCoupler,
                                          MultipolesPotentialCoupler)
from gpaw.grid_descriptor import GridDescriptor
from gpaw.mpi import world, serial_comm
from gpaw.poisson import PoissonSolver, FDPoissonSolver
from gpaw.tddft import TDDFT
from gpaw.transformers import Transformer
from gpaw.utilities.gpts import get_number_of_grid_points

# QSFDTD is a wrapper class to make calculations
# easier, something like this:
#      qsfdtd = QSFDTD(cl, at, c, h)
#      energy = qsfdtd.ground_state('gs.gpw')
#      qsfdtd.time_propagation('gs.gpw', kick)
#      photoabsorption_spectrum('dm.dat', 'spec.dat')


class QSFDTD:
    def __init__(self,
                 classical_material,
                 atoms,
                 cells,
                 spacings,
                 communicator=serial_comm,
                 remove_moments=(1, 1)):

        self.td_calc = None

        # Define classical cell in one of these ways:
        # 1. [cx, cy, cz]   -> vacuum for the quantum grid = 4.0
        # 2. ([cx, cy, cz]) -> vacuum = 4.0
        # 3. ([cx, cy, cz], vacuum)
        # 4. ([cx, cy, cz], ([p1x, p1y, p1z], [p2x, p2y, p2z]))
        #    where p1 and p2 are corners of the quantum grid
        if len(cells) == 1:  # (cell)
            assert (len(cells[0]) == 3)
            cell = np.array(cells[0])
            vacuum = 4.0
        elif len(cells) == 3:  # [cell.x, cell.y, cell.z]
            cell = np.array(cells)
            vacuum = 4.0
        elif len(cells) == 2:  # cell + vacuum/corners
            cell = np.array(cells[0])
            if np.array(cells[1]).size == 1:
                vacuum = cells[1]
                corners = None
            else:
                vacuum = None
                corners = cells[1]
        else:
            raise Exception('QSFDTD: cells defined incorrectly')

        # Define spacings in in one of these ways:
        # 1. (clh, qmh)
        # 2. clh -> qmh=clh/4
        if np.array(spacings).size == 1:  # clh
            cl_spacing = spacings
            qm_spacing = 0.25 * cl_spacing
        elif len(spacings) == 2:  # (clh, qmh)
            cl_spacing = spacings[0]
            qm_spacing = spacings[1]
        else:
            raise Exception('QSFDTD: spacings defined incorrectly')

        self.poissonsolver = FDTDPoissonSolver(
            classical_material=classical_material,
            cl_spacing=cl_spacing,
            qm_spacing=qm_spacing,
            remove_moments=remove_moments,
            communicator=communicator,
            cell=cell)
        self.poissonsolver.set_calculation_mode('iterate')

        # Quantum system
        if atoms is not None:
            assert (len(cells) == 2)
            assert (len(spacings) == 2)
            assert (len(remove_moments) == 2)
            self.atoms = atoms
            self.atoms.set_cell(cell)
            if vacuum is not None:  # vacuum
                self.atoms, self.qm_spacing, self.gpts = \
                    self.poissonsolver.cut_cell(self.atoms, vacuum=vacuum)
            else:  # corners
                self.atoms, self.qm_spacing, self.gpts = \
                    self.poissonsolver.cut_cell(self.atoms, corners=corners)
        else:  # Dummy quantum system
            self.atoms = Atoms('H', [0.5 * cell], cell=cell)
            if vacuum is not None:  # vacuum
                self.atoms, self.qm_spacing, self.gpts = \
                    self.poissonsolver.cut_cell(self.atoms, vacuum=vacuum)
            else:  # corners
                self.atoms, self.qm_spacing, self.gpts = \
                    self.poissonsolver.cut_cell(self.atoms, corners=corners)
            del self.atoms[:]

    def ground_state(self, filename, **kwargs):
        # GPAW calculator for the ground state
        self.gs_calc = GPAW(gpts=self.gpts,
                            poissonsolver=self.poissonsolver,
                            **kwargs)
        self.atoms.set_calculator(self.gs_calc)
        self.energy = self.atoms.get_potential_energy()
        self.write(filename, mode='all')

    def write(self, filename, **kwargs):
        if self.td_calc is None:
            self.gs_calc.write(filename, **kwargs)
        else:
            self.td_calc.write(filename, **kwargs)

    def time_propagation(self,
                         filename,
                         kick_strength,
                         time_step,
                         iterations,
                         dipole_moment_file=None,
                         restart_file=None,
                         dump_interval=100,
                         **kwargs):
        self.td_calc = TDDFT(filename, **kwargs)
        if kick_strength is not None:
            self.td_calc.absorption_kick(kick_strength)
            self.td_calc.hamiltonian.poisson.set_kick(kick_strength)
        self.td_calc.propagate(time_step, iterations, dipole_moment_file,
                               restart_file, dump_interval)


# This helps in telling the classical quantities from the quantum ones
class PoissonOrganizer:
    def __init__(self, poisson_solver=None):
        self.poisson_solver = poisson_solver
        self.gd = None
        self.density = None
        self.cell = None
        self.spacing_def = None
        self.spacing = None


# For mixing the potential
class SimpleMixer():
    def __init__(self, alpha, data):
        self.alpha = alpha
        self.data = np.copy(data)

    def mix(self, data):
        self.data = self.alpha * data + (1.0 - self.alpha) * self.data
        return np.copy(self.data)


# Contains one PoissonSolver for the classical
# and one for the quantum subsystem
class FDTDPoissonSolver:
    def __init__(self,
                 nn=3,
                 relax='J',
                 eps=1e-24,
                 classical_material=None,
                 cell=None,
                 qm_spacing=0.30,
                 cl_spacing=1.20,
                 remove_moments=(1, 1),
                 potential_coupler='Refiner',
                 communicator=serial_comm):

        self.rank = mpi.rank

        self.messages = []

        assert (potential_coupler in ['Multipoles', 'Refiner'])
        self.potential_coupling_scheme = potential_coupler

        if classical_material is None:
            self.classical_material = PolarizableMaterial()
        else:
            self.classical_material = classical_material

        self.set_calculation_mode('solve')

        self.has_subsystems = False
        self.remove_moment_cl = remove_moments[0]
        self.remove_moment_qm = remove_moments[1]
        self.time = 0.0
        self.time_step = 0.0
        self.kick = np.array([0.0, 0.0, 0.0], dtype=float)
        self.maxiter = 2000
        self.eps = eps
        self.relax = relax
        self.nn = nn

        # Only handle the quantities via self.qm or self.cl
        self.cl = PoissonOrganizer()
        self.cl.spacing_def = cl_spacing * np.ones(3) / Bohr
        self.cl.extrapolated_qm_phi = None
        self.cl.dcomm = communicator
        self.cl.dparsize = None
        self.qm = PoissonOrganizer(FDPoissonSolver)  # Default solver
        self.qm.spacing_def = qm_spacing * np.ones(3) / Bohr
        self.qm.cell = np.array(cell) / Bohr

        # Classical spacing and simulation cell
        _cell = np.array(cell) / Bohr
        self.cl.spacing = self.cl.spacing_def
        if np.size(_cell) == 3:
            self.cl.cell = np.diag(_cell)
        else:
            self.cl.cell = _cell

        # Generate classical grid descriptor
        self.initialize_clgd()

    def todict(self):
        dct = dict(
            name='fdtd',
            nn=self.nn,
            relax=self.relax,
            eps=self.eps,
            # classical_material missing
            cell=self.cl.cell * Bohr,
            qm_spacing=self.qm.spacing_def[0] * Bohr,
            cl_spacing=self.cl.spacing_def[0] * Bohr,
            remove_moments=(self.remove_moment_cl, self.remove_moment_qm),
            potential_coupler=self.potential_coupling_scheme)

        return dct

    def get_description(self):
        return 'FDTD+TDDFT'

    # Generated classical GridDescriptors, after spacing and cell are known
    def initialize_clgd(self):
        N_c = get_number_of_grid_points(self.cl.cell, self.cl.spacing)
        self.cl.spacing = np.diag(self.cl.cell) / N_c
        self.cl.gd = GridDescriptor(N_c, self.cl.cell, False, self.cl.dcomm,
                                    self.cl.dparsize)
        self.cl.gd_global = GridDescriptor(N_c, self.cl.cell, False,
                                           serial_comm, None)
        self.cl.extrapolated_qm_phi = self.cl.gd.empty()

    def estimate_memory(self, mem):
        # self.cl.poisson_solver.estimate_memory(mem)
        #print(self.qm.poisson_solver.estimate_memory.__code__.co_varnames)
        # WTF?  How can this shabby method suddenly be unbound?  It needs both self and mem.
        # Ferchrissakes!
        #self.qm.poisson_solver.estimate_memory(mem=mem)
        pass

    # Return the TDDFT stencil by default
    def get_stencil(self, mode='qm'):
        if mode == 'qm':
            return self.qm.poisson_solver.get_stencil()
        else:
            return self.cl.poisson_solver.get_stencil()

    # Initialize both PoissonSolvers
    #def initialize(self):
    #    self.qm.poisson_solver._init()
    #    self.cl.poisson_solver._init()

    def set_grid_descriptor(self, qmgd):
        if not self.has_subsystems:
            return

        self.qm.gd = qmgd

        # Create quantum Poisson solver
        self.qm.poisson_solver = PoissonSolver(
            name='fd',
            nn=self.nn,
            eps=self.eps,
            relax=self.relax,
            remove_moment=self.remove_moment_qm)
        self.qm.poisson_solver.set_grid_descriptor(self.qm.gd)
        #self.qm.poisson_solver.initialize()
        self.qm.phi = self.qm.gd.zeros()
        self.qm.rho = self.qm.gd.zeros()

        # Set quantum grid descriptor
        self.qm.poisson_solver.set_grid_descriptor(qmgd)

        # Create classical PoissonSolver
        self.cl.poisson_solver = PoissonSolver(
            name='fd',
            nn=self.nn,
            eps=self.eps,
            relax=self.relax,
            remove_moment=self.remove_moment_cl)
        self.cl.poisson_solver.set_grid_descriptor(self.cl.gd)
        #self.cl.poisson_solver.initialize()

        # Initialize classical material,
        # its Poisson solver was generated already
        self.cl.poisson_solver.set_grid_descriptor(self.cl.gd)
        self.classical_material.initialize(self.cl.gd)
        self.cl.extrapolated_qm_phi = self.cl.gd.zeros()
        self.cl.phi = self.cl.gd.zeros()
        self.cl.extrapolated_qm_phi = self.cl.gd.empty()

        msg = self.messages.append
        msg('\nFDTDPoissonSolver/grid descriptors and coupler:')
        msg(' Domain parallelization with %i processes.' %
            self.cl.gd.comm.size)
        if self.cl.gd.comm == serial_comm:
            msg(' Communicator for domain parallelization: serial_comm')
        elif self.cl.gd.comm == world:
            msg(' Communicator for domain parallelization: world')
        elif self.cl.gd.comm == self.qm.gd.comm:
            msg(' Communicator for domain parallelization: dft_domain_comm')
        else:
            msg(' Communicator for domain parallelization: %s'
                % self.cl.gd.comm)

        # Initialize potential coupler
        if self.potential_coupling_scheme == 'Multipoles':
            msg('Classical-quantum coupling by multipole expansion ' +
                'with maxL: %i' % (self.remove_moment_qm))
            self.potential_coupler = MultipolesPotentialCoupler(
                qm=self.qm,
                cl=self.cl,
                index_offset_1=self.shift_indices_1,
                index_offset_2=self.shift_indices_2,
                extended_index_offset_1=self.extended_shift_indices_1,
                extended_index_offset_2=self.extended_shift_indices_2,
                extended_delta_index=self.extended_deltaIndex,
                num_refinements=self.num_refinements,
                remove_moment_qm=self.remove_moment_qm,
                remove_moment_cl=self.remove_moment_cl,
                rank=self.rank)
        else:
            msg('Classical-quantum coupling by coarsening/refining')
            self.potential_coupler = RefinerPotentialCoupler(
                qm=self.qm,
                cl=self.cl,
                index_offset_1=self.shift_indices_1,
                index_offset_2=self.shift_indices_2,
                extended_index_offset_1=self.extended_shift_indices_1,
                extended_index_offset_2=self.extended_shift_indices_2,
                extended_delta_index=self.extended_deltaIndex,
                num_refinements=self.num_refinements,
                remove_moment_qm=self.remove_moment_qm,
                remove_moment_cl=self.remove_moment_cl,
                rank=self.rank)

        self.phi_tot_clgd = self.cl.gd.empty()
        self.phi_tot_qmgd = self.qm.gd.empty()

    def cut_cell(self,
                 atoms_in,
                 vacuum=5.0,
                 corners=None,
                 create_subsystems=True):
        qmh = self.qm.spacing_def
        if corners is not None:
            v1 = np.array(corners[0]).ravel() / Bohr
            v2 = np.array(corners[1]).ravel() / Bohr
        else:  # Use vacuum
            pos_old = atoms_in.get_positions()[0]
            dmy_atoms = atoms_in.copy()
            dmy_atoms.center(vacuum=vacuum)
            pos_new = dmy_atoms.get_positions()[0]
            v1 = (pos_old - pos_new) / Bohr
            v2 = v1 + np.diag(dmy_atoms.get_cell()) / Bohr

        # Needed for restarting
        self.given_corner_v1 = v1 * Bohr
        self.given_corner_v2 = v2 * Bohr
        self.given_cell = atoms_in.get_cell()

        # Sanity check: quantum box must be inside the classical one
        assert (all([v1[w] <= v2[w] and v1[w] >= 0 and
                     v2[w] <= np.diag(self.cl.cell)[w] for w in range(3)]))

        # Ratios of the user-given spacings
        self.hratios = self.cl.spacing_def / qmh
        self.num_refinements = \
            1 + int(round(np.log(self.hratios[0]) / np.log(2.0)))
        assert ([int(round(np.log(self.hratios[w]) / np.log(2.0))) ==
                 self.num_refinements for w in range(3)])

        # Create quantum grid
        self.qm.cell = np.zeros((3, 3))
        for w in range(3):
            self.qm.cell[w, w] = v2[w] - v1[w]

        N_c = get_number_of_grid_points(self.qm.cell, qmh)
        self.qm.spacing = np.diag(self.qm.cell) / N_c

        # Classical corner indices must be divisible with numb
        if any(self.cl.spacing / self.qm.spacing >= 3):
            numb = 1
        elif any(self.cl.spacing / self.qm.spacing >= 2):
            numb = 2
        else:
            numb = 4

        # The index mismatch of the two simulation cells
        # Round before taking floor/ceil to avoid floating point
        # arithmetic errors
        num_indices_1 = numb * np.floor(
            np.round(np.array(v1) / self.cl.spacing / numb, 2)).astype(int)
        num_indices_2 = numb * np.ceil(
            np.round(np.array(v2) / self.cl.spacing / numb, 2)).astype(int)
        self.num_indices = num_indices_2 - num_indices_1

        # Center, left, and right points of the suggested quantum grid
        cp = 0.5 * (np.array(v1) + np.array(v2))
        lp = cp - 0.5 * self.num_indices * self.cl.spacing
        # rp = cp + 0.5 * self.num_indices * self.cl.spacing

        # Indices in the classical grid restricting the quantum grid
        self.shift_indices_1 = np.round(lp / self.cl.spacing).astype(int)
        self.shift_indices_2 = self.shift_indices_1 + self.num_indices

        # Sanity checks
        assert(all([self.shift_indices_1[w] >= 0 and
                    self.shift_indices_2[w] <= self.cl.gd.N_c[w]
                    for w in range(3)])), \
            "Could not find appropriate quantum grid. " + \
            "Move it further away from the boundary."

        # Corner coordinates
        self.qm.corner1 = self.shift_indices_1 * self.cl.spacing
        self.qm.corner2 = self.shift_indices_2 * self.cl.spacing

        # Now the information for creating the subsystems is ready
        if create_subsystems:
            return self.create_subsystems(atoms_in)

    def create_subsystems(self, atoms_in):

        # Create new Atoms object
        atoms_out = atoms_in.copy()

        # New quantum grid
        self.qm.cell = \
            np.diag([(self.shift_indices_2[w] - self.shift_indices_1[w]) *
                     self.cl.spacing[w] for w in range(3)])
        self.qm.spacing = self.cl.spacing / self.hratios
        N_c = get_number_of_grid_points(self.qm.cell, self.qm.spacing)

        atoms_out.set_cell(np.diag(self.qm.cell) * Bohr)
        atoms_out.positions = atoms_in.get_positions() - self.qm.corner1 * Bohr

        msg = self.messages.append
        msg("Quantum box readjustment:")
        msg("  Given cell:       [%10.5f %10.5f %10.5f]" %
            tuple(np.diag(atoms_in.get_cell())))
        msg("  Given atomic coordinates:")
        for s, c in zip(atoms_in.get_chemical_symbols(),
                        atoms_in.get_positions()):
            msg("              %s %10.5f %10.5f %10.5f" %
                (s, c[0], c[1], c[2]))
        msg("  Readjusted cell:  [%10.5f %10.5f %10.5f]" %
            tuple(np.diag(atoms_out.get_cell())))
        msg("  Readjusted atomic coordinates:")
        for s, c in zip(atoms_out.get_chemical_symbols(),
                        atoms_out.get_positions()):
            msg("              %s %10.5f %10.5f %10.5f" %
                (s, c[0], c[1], c[2]))

        msg("  Given corner points:       " +
            "(%10.5f %10.5f %10.5f) - (%10.5f %10.5f %10.5f)"
            % (tuple(np.concatenate((self.given_corner_v1,
                                     self.given_corner_v2)))))
        msg("  Readjusted corner points:  " +
            "(%10.5f %10.5f %10.5f) - (%10.5f %10.5f %10.5f)"
            % (tuple(np.concatenate((self.qm.corner1,
                                     self.qm.corner2)) * Bohr)))
        msg("  Indices in classical grid: " +
            "(%10i %10i %10i) - (%10i %10i %10i)"
            % (tuple(np.concatenate((self.shift_indices_1,
                                     self.shift_indices_2)))))
        msg("  Grid points in classical grid: " +
            "(%10i %10i %10i)"
            % (tuple(self.cl.gd.N_c)))
        msg("  Grid points in quantum grid:   " +
            "(%10i %10i %10i)"
            % (tuple(N_c)))
        msg("  Spacings in quantum grid:    " +
            "(%10.5f %10.5f %10.5f)"
            % (tuple(np.diag(self.qm.cell) * Bohr / N_c)))
        msg("  Spacings in classical grid:  " +
            "(%10.5f %10.5f %10.5f)"
            % (tuple(np.diag(self.cl.cell) *
                     Bohr / get_number_of_grid_points(self.cl.cell,
                                                      self.cl.spacing))))
        # msg("  Ratios of cl/qm spacings:    " +
        #    "(%10i %10i %10i)" % (tuple(self.hratios)))
        # msg("                             = (%10.2f %10.2f %10.2f)" %
        #         (tuple((np.diag(self.cl.cell) * Bohr / \
        #                 get_number_of_grid_points(self.cl.cell,
        #                                           self.cl.spacing)) / \
        #                (np.diag(self.qm.cell) * Bohr / N_c))))
        msg("  Needed number of refinements: %10i"
            % self.num_refinements)

        # First, create the quantum grid equivalent GridDescriptor
        # self.cl.subgd. Then coarsen it until its h_cv equals
        # that of self.cl.gd. Finally, map the points between
        # clgd and coarsened subgrid.
        subcell_cv = np.diag(self.qm.corner2 - self.qm.corner1)
        N_c = get_number_of_grid_points(subcell_cv, self.cl.spacing)
        N_c = self.shift_indices_2 - self.shift_indices_1
        self.cl.subgds = []
        self.cl.subgds.append(GridDescriptor(N_c, subcell_cv, False,
                                             serial_comm, self.cl.dparsize))

        # msg("  N_c/spacing of the subgrid:           " +
        #    "%3i %3i %3i / %.4f %.4f %.4f" %
        #          (self.cl.subgds[0].N_c[0],
        #           self.cl.subgds[0].N_c[1],
        #           self.cl.subgds[0].N_c[2],
        #           self.cl.subgds[0].h_cv[0][0] * Bohr,
        #           self.cl.subgds[0].h_cv[1][1] * Bohr,
        #           self.cl.subgds[0].h_cv[2][2] * Bohr))
        # msg("  shape from the subgrid:           " +
        #    "%3i %3i %3i" % (tuple(self.cl.subgds[0].empty().shape)))

        self.cl.coarseners = []
        self.cl.refiners = []
        for n in range(self.num_refinements):
            self.cl.subgds.append(self.cl.subgds[n].refine())
            self.cl.refiners.append(Transformer(self.cl.subgds[n],
                                                self.cl.subgds[n + 1]))

            # msg("  refiners[%i] can perform the transformation " +
            #    "(%3i %3i %3i) -> (%3i %3i %3i)" % (\
            #         n,
            #         self.cl.subgds[n].empty().shape[0],
            #         self.cl.subgds[n].empty().shape[1],
            #         self.cl.subgds[n].empty().shape[2],
            #         self.cl.subgds[n + 1].empty().shape[0],
            #         self.cl.subgds[n + 1].empty().shape[1],
            #         self.cl.subgds[n + 1].empty().shape[2]))
            self.cl.coarseners.append(Transformer(self.cl.subgds[n + 1],
                                                  self.cl.subgds[n]))
        self.cl.coarseners[:] = self.cl.coarseners[::-1]

        # Now extend the grid in order to handle
        # the zero boundary conditions that the refiner assumes
        # The default interpolation order
        self.extend_nn = \
            Transformer(GridDescriptor([8, 8, 8], [1, 1, 1],
                                       False, serial_comm, None),
                        GridDescriptor([8, 8, 8], [1, 1, 1],
                                       False, serial_comm, None).coarsen()).nn

        self.extended_num_indices = self.num_indices + [2, 2, 2]

        # Center, left, and right points of the suggested quantum grid
        extended_cp = 0.5 * (np.array(self.given_corner_v1 / Bohr) +
                             np.array(self.given_corner_v2 / Bohr))
        extended_lp = extended_cp - 0.5 * (self.extended_num_indices *
                                           self.cl.spacing)
        # extended_rp = extended_cp + 0.5 * (self.extended_num_indices *
        #                                    self.cl.spacing)

        # Indices in the classical grid restricting the quantum grid
        self.extended_shift_indices_1 = \
            np.round(extended_lp / self.cl.spacing).astype(int)
        self.extended_shift_indices_2 = \
            self.extended_shift_indices_1 + self.extended_num_indices

        # msg('  extended_shift_indices_1: %i %i %i'
        #     % (self.extended_shift_indices_1[0],
        #        self.extended_shift_indices_1[1],
        #        self.extended_shift_indices_1[2]))
        # msg('  extended_shift_indices_2: %i %i %i'
        #     % (self.extended_shift_indices_2[0],
        #        self.extended_shift_indices_2[1],
        #        self.extended_shift_indices_2[2]))
        # msg('  cl.gd.N_c:                %i %i %i'
        #     % (self.cl.gd.N_c[0], self.cl.gd.N_c[1], self.cl.gd.N_c[2]))

        # Sanity checks
        assert(all([self.extended_shift_indices_1[w] >= 0 and
                    self.extended_shift_indices_2[w] <= self.cl.gd.N_c[w]
                    for w in range(3)])), \
            "Could not find appropriate quantum grid. " + \
            "Move it further away from the boundary."

        # Corner coordinates
        self.qm.extended_corner1 = \
            self.extended_shift_indices_1 * self.cl.spacing
        self.qm.extended_corner2 = \
            self.extended_shift_indices_2 * self.cl.spacing
        N_c = self.extended_shift_indices_2 - self.extended_shift_indices_1

        self.cl.extended_subgds = []
        self.cl.extended_refiners = []
        extended_subcell_cv = np.diag(self.qm.extended_corner2 -
                                      self.qm.extended_corner1)

        self.cl.extended_subgds.append(GridDescriptor(
            N_c, extended_subcell_cv, False, serial_comm, None))

        for n in range(self.num_refinements):
            self.cl.extended_subgds.append(self.cl.extended_subgds[n].refine())
            self.cl.extended_refiners.append(Transformer(
                self.cl.extended_subgds[n], self.cl.extended_subgds[n + 1]))

            # msg("  extended_refiners[%i] can perform the transformation " +
            #     "(%3i %3i %3i) -> (%3i %3i %3i)"
            #     % (n,
            #        self.cl.extended_subgds[n].empty().shape[0],
            #        self.cl.extended_subgds[n].empty().shape[1],
            #        self.cl.extended_subgds[n].empty().shape[2],
            #        self.cl.extended_subgds[n + 1].empty().shape[0],
            #        self.cl.extended_subgds[n + 1].empty().shape[1],
            #        self.cl.extended_subgds[n + 1].empty().shape[2]))

            # msg("  N_c/spacing of the refined subgrid:   " +
            #     "%3i %3i %3i / %.4f %.4f %.4f"
            #     % (self.cl.subgds[-1].N_c[0],
            #        self.cl.subgds[-1].N_c[1],
            #        self.cl.subgds[-1].N_c[2],
            #        self.cl.subgds[-1].h_cv[0][0] * Bohr,
            #        self.cl.subgds[-1].h_cv[1][1] * Bohr,
            #        self.cl.subgds[-1].h_cv[2][2] * Bohr))
            # msg("  shape from the refined subgrid:       %3i %3i %3i"
            #     % (tuple(self.cl.subgds[-1].empty().shape)))

        self.extended_deltaIndex = 2**(self.num_refinements) * self.extend_nn
        # msg(" self.extended_deltaIndex = %i" % self.extended_deltaIndex)

        qgpts = self.cl.subgds[-1].coarsen().N_c

        # Assure that one returns to the original shape
        dmygd = self.cl.subgds[-1].coarsen()
        for n in range(self.num_refinements - 1):
            dmygd = dmygd.coarsen()

        # msg("  N_c/spacing of the coarsened subgrid: " +
        #     "%3i %3i %3i / %.4f %.4f %.4f"
        #     % (dmygd.N_c[0], dmygd.N_c[1], dmygd.N_c[2],
        #        dmygd.h_cv[0][0] * Bohr,
        #        dmygd.h_cv[1][1] * Bohr,
        #        dmygd.h_cv[2][2] * Bohr))

        self.has_subsystems = True
        return atoms_out, self.qm.spacing[0] * Bohr, qgpts

    def print_messages(self, printer_function):
        printer_function("\n *** QSFDTD ***\n")
        for msg in self.messages:
            printer_function(msg)

        for msg in self.classical_material.messages:
            printer_function(msg)
        printer_function("\n *********************\n")

    # Set the time step
    def set_time_step(self, time_step):
        self.time_step = time_step

    # Set the time
    def set_time(self, time):
        self.time = time

    # Setup kick
    def set_kick(self, kick):
        self.kick = np.array(kick)

    def finalize_propagation(self):
        pass

    def set_calculation_mode(self, calculation_mode):
        # Three calculation modes are available:
        #  1) solve:     just solve the Poisson equation with
        #                given quantum+classical rho
        #  2) iterate:   iterate classical density so that the Poisson
        #                equation for quantum+classical rho is satisfied
        #  3) propagate: propagate classical density in time, and solve
        #                the new Poisson equation
        assert (calculation_mode == 'solve' or calculation_mode == 'iterate' or
                calculation_mode == 'propagate')
        self.calculation_mode = calculation_mode

    # The density object must be attached, so that the electric field
    # from all-electron density can be calculated
    def set_density(self, density):
        self.density = density

    # Returns the classical density and the grid descriptor
    def get_density(self, global_array=False):
        if global_array:
            return \
                self.cl.gd.collect(self.classical_material.charge_density) * \
                self.classical_material.sign, \
                self.cl.gd
        else:
            return \
                self.classical_material.charge_density * \
                self.classical_material.sign, \
                self.cl.gd

    # Returns the quantum + classical density in the large classical box,
    # so that the classical charge is refined into it and the quantum
    # charge is coarsened there
    def get_combined_data(self, qmdata=None, cldata=None, spacing=None,
                          qmgd=None, clgd=None):

        if qmdata is None:
            qmdata = self.density.rhot_g

        if cldata is None:
            cldata = (self.classical_material.charge_density *
                      self.classical_material.sign)

        if qmgd is None:
            qmgd = self.qm.gd

        if clgd is None:
            clgd = self.cl.gd

        if spacing is None:
            spacing = clgd.h_cv[0, 0]

        spacing_au = spacing / Bohr  # from Angstroms to a.u.

        # Refine classical part
        clgd = clgd.new_descriptor()
        cl_g = cldata.copy()
        while clgd.h_cv[0, 0] > spacing_au * 1.50:  # 45:
            clgd2 = clgd.refine()
            cl_g = Transformer(clgd, clgd2).apply(cl_g)
            clgd = clgd2

        # Coarse quantum part
        qmgd = qmgd.new_descriptor()
        qm_g = qmdata.copy()
        while qmgd.h_cv[0, 0] < clgd.h_cv[0, 0] * 0.95:
            qmgd2 = qmgd.coarsen()
            qm_g = Transformer(qmgd, qmgd2).apply(qm_g)
            qmgd = qmgd2

        assert np.all(np.absolute(qmgd.h_cv - clgd.h_cv) < 1e-12), \
            " Spacings %.8f (qm) and %.8f (cl) Angstroms" \
            % (qmgd.h_cv[0][0] * Bohr, clgd.h_cv[0][0] * Bohr)

        # Do distribution on master
        big_cl_g = clgd.collect(cl_g)
        big_qm_g = qmgd.collect(qm_g, broadcast=True)

        if clgd.comm.rank == 0:
            # now find the corners
            # r_gv_cl = \
            #     clgd.get_grid_point_coordinates().transpose((1, 2, 3, 0))
            cind = (self.qm.corner1 / np.diag(clgd.h_cv) - 1).astype(int)

            n = big_qm_g.shape

            # print 'Corner points:     ', self.qm.corner1*Bohr, \
            #     ' - ', self.qm.corner2*Bohr
            # print 'Calculated points: ', r_gv_cl[tuple(cind)]*Bohr, \
            #     ' - ', r_gv_cl[tuple(cind+n+1)]*Bohr

            big_cl_g[cind[0] + 1:cind[0] + n[0] + 1,
                     cind[1] + 1:cind[1] + n[1] + 1,
                     cind[2] + 1:cind[2] + n[2] + 1] += big_qm_g

        clgd.distribute(big_cl_g, cl_g)
        return cl_g, clgd

    # Solve quantum and classical potentials, and add them up
    def solve_solve(self, **kwargs):
        self.phi_tot_qmgd, self.phi_tot_clgd, niter = \
            self.potential_coupler.getPotential(
                local_rho_qm_qmgd=self.qm.rho,
                local_rho_cl_clgd=self.classical_material.sign *
                self.classical_material.charge_density,
                **kwargs)
        self.qm.phi[:] = self.phi_tot_qmgd[:]
        self.cl.phi[:] = self.phi_tot_clgd[:]
        return niter

    # Iterate classical and quantum potentials until convergence
    def solve_iterate(self, **kwargs):
        # Initial value (unefficient?)
        self.solve_solve(**kwargs)
        old_rho_qm = self.qm.rho.copy()
        old_rho_cl = self.classical_material.charge_density.copy()

        niter_cl = 0

        while True:
            # field from the potential
            # E = -Div[Vh]
            self.classical_material.solve_electric_field(self.cl.phi)

            # Polarizations P0_j and Ptot
            # P = (eps - eps0)E
            self.classical_material.solve_polarizations()

            # Classical charge density
            # n = -Grad[P]
            self.classical_material.solve_rho()

            # Update electrostatic potential
            # nabla^2 Vh = -4*pi*n
            niter = self.solve_solve(**kwargs)

            # Mix potential
            try:
                self.mix_phi
            except:
                self.mix_phi = SimpleMixer(0.10, self.qm.phi)

            self.qm.phi = self.mix_phi.mix(self.qm.phi)

            # Check convergence
            niter_cl += 1

            dRho = self.qm.gd.integrate(abs(self.qm.rho - old_rho_qm)) + \
                self.cl.gd.integrate(
                    abs(self.classical_material.charge_density - old_rho_cl))

            if (abs(dRho) < 1e-3):
                break
            old_rho_qm = self.qm.rho.copy()
            old_rho_cl = (self.classical_material.sign *
                          self.classical_material.charge_density).copy()

        return (niter, niter_cl)

    def solve_propagate(self, **kwargs):

        # 1) P(t) from P(t-dt) and J(t-dt/2)
        self.classical_material.propagate_polarizations(self.time_step)

        # 2) n(t) from P(t)
        self.classical_material.solve_rho()

        # 3a) V(t) from n(t)
        niter = self.solve_solve(**kwargs)

        # 4a) E(r) from V(t):      E = -Div[Vh]
        self.classical_material.solve_electric_field(self.cl.phi)

        # 4b) Apply the kick by changing the electric field
        if self.time == 0:
            self.cl.rho_gs = self.classical_material.charge_density.copy()
            self.qm.rho_gs = self.qm.rho.copy()
            self.cl.phi_gs = self.cl.phi.copy()
            self.cl.extrapolated_qm_phi_gs = self.cl.gd.zeros()
            self.qm.phi_gs = self.qm.phi.copy()
            self.classical_material.kick_electric_field(self.time_step,
                                                        self.kick)

        # 5) J(t+dt/2) from J(t-dt/2) and P(t)
        self.classical_material.propagate_currents(self.time_step)

        # Update timer
        self.time = self.time + self.time_step

        # Do not propagate before the next time step
        self.set_calculation_mode('solve')

        return niter

    def solve(self,
              phi,
              rho,
              charge=None,
              eps=None,
              maxcharge=1e-6,
              zero_initial_phi=False,
              calculation_mode=None,
              timer=None):

        if self.density is None:
            raise RuntimeError('FDTDPoissonSolver requires a density object.'
                               ' Use set_density routine to initialize it.')

        # Update local variables (which may
        # have changed in SCF cycle or propagator)
        self.qm.phi = phi
        self.qm.rho = rho

        if (self.calculation_mode == 'solve'):
            # do not modify the polarizable material
            niter = self.solve_solve(charge=None,
                                     eps=eps,
                                     maxcharge=maxcharge,
                                     zero_initial_phi=False)

        elif (self.calculation_mode == 'iterate'):
            # find self-consistent density
            niter = self.solve_iterate(charge=None,
                                       eps=eps,
                                       maxcharge=maxcharge,
                                       zero_initial_phi=False)

        elif (self.calculation_mode == 'propagate'):
            # propagate one time step
            niter = self.solve_propagate(charge=None,
                                         eps=eps,
                                         maxcharge=maxcharge,
                                         zero_initial_phi=False)

        phi = self.qm.phi
        rho = self.qm.rho

        return niter

    # Classical contribution. Note the different origin.
    def get_classical_dipole_moment(self):
        r_gv = self.cl.gd.get_grid_point_coordinates().transpose((
            1, 2, 3, 0)) - self.qm.corner1
        return -1.0 * self.classical_material.sign * np.array(
            [self.cl.gd.integrate(np.multiply(
                r_gv[:, :, :, w] + self.qm.corner1[w],
                self.classical_material.charge_density)) for w in range(3)])

    # Quantum contribution
    def get_quantum_dipole_moment(self):
        return self.density.finegd.calculate_dipole_moment(self.density.rhot_g)

    # Read restart data
    def read(self, reader):
        r = reader.hamiltonian.poisson

        # FDTDPoissonSolver related data
        self.description = r.description
        self.time = r.time
        self.time_step = r.time_step

        # Try to read time-dependent information
        self.kick = r.kick
        self.maxiter = r.maxiter

        # PoissonOrganizer: classical
        self.cl = PoissonOrganizer()
        self.cl.spacing_def = r.cl_spacing_def
        self.cl.spacing = r.cl_spacing
        self.cl.cell = np.diag(r.cl_cell)
        self.cl.dparsize = None

        # TODO: it should be possible to use different
        #       communicator after restart
        if r.cl_world_comm:
            self.cl.dcomm = world
        else:
            self.cl.dcomm = mpi.serial_comm

        # Generate classical grid descriptor
        self.initialize_clgd()

        # Classical materials data
        self.classical_material = PolarizableMaterial()
        self.classical_material.read(r)
        self.classical_material.initialize(self.cl.gd)

        # PoissonOrganizer: quantum
        self.qm = PoissonOrganizer()
        self.qm.corner1 = r.qm_corner1
        self.qm.corner2 = r.qm_corner2
        self.given_corner_v1 = r.given_corner_1
        self.given_corner_v2 = r.given_corner_2
        self.given_cell = np.diag(r.given_cell)
        self.hratios = r.hratios
        self.shift_indices_1 = r.shift_indices_1.astype(int)
        self.shift_indices_2 = r.shift_indices_2.astype(int)
        self.num_indices = r.num_indices.astype(int)
        self.num_refinements = int(r.num_refinements)

        # Redefine atoms to suit the cut_cell routine
        newatoms = read_atoms(reader.atoms)
        newatoms.positions = newatoms.positions + self.qm.corner1 * Bohr
        newatoms.set_cell(np.diag(self.given_cell))
        self.create_subsystems(newatoms)

        # Read self.classical_material.charge_density
        if self.cl.gd.comm.rank == 0:
            big_charge_density = \
                np.array(r.get('classical_material_rho'), dtype=float)
        else:
            big_charge_density = None
        self.cl.gd.distribute(big_charge_density,
                              self.classical_material.charge_density)

        # Read self.classical_material.polarization_total
        if self.cl.gd.comm.rank == 0:
            big_polarization_total = \
                np.array(r.get('polarization_total'), dtype=float)
        else:
            big_polarization_total = None
        self.cl.gd.distribute(big_polarization_total,
                              self.classical_material.polarization_total)

        # Read self.classical_material.polarizations
        if self.cl.gd.comm.rank == 0:
            big_polarizations = np.array(r.get('polarizations'), dtype=float)
        else:
            big_polarizations = None
        self.cl.gd.distribute(big_polarizations,
                              self.classical_material.polarizations)

        # Read self.classical_material.currents
        if self.cl.gd.comm.rank == 0:
            big_currents = np.array(r.get('currents'), dtype=float)
        else:
            big_currents = None
        self.cl.gd.distribute(big_currents, self.classical_material.currents)

    def write(self, writer):
        # Classical materials data
        self.classical_material.write(writer.child('classmat'))

        # FDTDPoissonSolver related data
        writer.write(
            description=self.get_description(),
            time=self.time,
            time_step=self.time_step,
            kick=self.kick,
            maxiter=self.maxiter,
            # PoissonOrganizer
            cl_cell=np.diag(self.cl.cell),
            cl_spacing_def=self.cl.spacing_def,
            cl_spacing=self.cl.spacing,
            cl_world_comm=self.cl.dcomm == world,
            qm_corner1=self.qm.corner1,
            qm_corner2=self.qm.corner2,
            given_corner_1=self.given_corner_v1,
            given_corner_2=self.given_corner_v2,
            given_cell=np.diag(self.given_cell),
            hratios=self.hratios,
            shift_indices_1=self.shift_indices_1,
            shift_indices_2=self.shift_indices_2,
            num_refinements=self.num_refinements,
            num_indices=self.num_indices)

        # Write the classical charge density
        charge_density = self.cl.gd.collect(
            self.classical_material.charge_density)
        writer.write(classical_material_rho=charge_density)

        # Write the total polarization
        polarization_total = self.cl.gd.collect(
            self.classical_material.polarization_total)
        writer.write(polarization_total=polarization_total)

        # Write the partial polarizations
        polarizations = self.cl.gd.collect(
            self.classical_material.polarizations)
        writer.write(polarizations=polarizations)

        # Write the partial currents
        currents = self.cl.gd.collect(self.classical_material.currents)
        writer.write(currents=currents)
