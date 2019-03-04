import ase.io
from gpaw import GPAW
atoms = ase.io.read('alpra_Mg.CONTCAR')
atoms.pbc = True
atoms.calc = GPAW(xc='vdW-DF',
                  occupations={'name': 'fermi-dirac', 'width': 0.1})
ncpus = 16
