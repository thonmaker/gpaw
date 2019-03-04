from ase import Atoms
from ase.parallel import paropen
from gpaw import GPAW
from gpaw.mixer import Mixer
from gpaw.eigensolvers import CG
from gpaw.poisson import PoissonSolver
from gpaw import setup_paths
setup_paths.insert(0, '.')

# Usual GPAW definitions
h = 0.18
a = 12.00
c = a/2

# XC functional + kinetic functional (minus the Tw contribution) to be used
xcname = '1.0_LDA_K_TF+1.0_LDA_X+1.0_LDA_C_PW'

# Fraction of Tw
lambda_coeff = 1.0

name = 'lambda_{0}'.format(lambda_coeff)

filename = 'atoms_'+name+'.dat'

f = paropen(filename,'w')

elements = ['N']

for symbol in elements:
    mixer = Mixer()

    eigensolver = CG(tw_coeff=lambda_coeff)

    poissonsolver=PoissonSolver()
    molecule = Atoms(symbol,
                     positions=[(c,c,c)] ,
                     cell=(a,a,a))

    calc = GPAW(h=h,
                xc=xcname,
                maxiter=240,
                eigensolver=eigensolver,
                mixer=mixer,
                setups=name,
                poissonsolver=poissonsolver)

    molecule.set_calculator(calc)

    E = molecule.get_total_energy()

    f.write('{0}\t{1}\n'.format(symbol,E))
