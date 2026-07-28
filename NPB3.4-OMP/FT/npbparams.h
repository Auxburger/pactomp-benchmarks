! CLASS = C
!  
!  
!  This file is generated automatically by the setparams utility.
!  It sets the number of processors and the class of the NPB
!  in this directory. Do not modify it by hand.
!  
        integer nx, ny, nz, maxdim, niter_default
        parameter (nx=512, ny=512, nz=512, maxdim=512)
        parameter (niter_default=20)
        integer kind2
        parameter (kind2=4)
        logical  convertdouble
        parameter (convertdouble = .false.)
        character compiletime*11
        parameter (compiletime='18 Feb 2026')
        character npbversion*5
        parameter (npbversion='3.4.3')
        character cs1*8
        parameter (cs1='gfortran')
        character cs2*5
        parameter (cs2='$(FC)')
        character cs3*46
        parameter (cs3='-L/dss/dsshome1/09/ga27qam2/llvm-project/bu...')
        character cs4*6
        parameter (cs4='(none)')
        character cs5*12
        parameter (cs5='-O3 -fopenmp')
        character cs6*12
        parameter (cs6='-O3 -fopenmp')
        character cs7*6
        parameter (cs7='randi8')
