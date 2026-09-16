import hashlib,json,platform,subprocess
from pathlib import Path
R=Path(__file__).resolve().parents[2];O=Path(__file__).resolve().parent
manifest={'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),'platform':platform.platform(),'cpu':subprocess.check_output(['lscpu'],text=True),'gcc':subprocess.check_output(['gcc','--version'],text=True),'clang':subprocess.check_output(['/usr/bin/clang-21','--version'],text=True),'files':{}}
for d in [R/'build-method-jit',R/'build-method-debug',R/'build-method-ft-debug',R/'build-method-ft-jit',O/'main-build',O/'profile-build']:
 files=[d/'python',d/'Makefile',d/'pyconfig.h',*d.glob('python-*'),*d.glob('jit_stencils*.h'),*d.glob('build/lib.*/*.so')]
 for p in files:
  if p.is_file():manifest['files'][str(p.relative_to(R))]=hashlib.sha256(p.read_bytes()).hexdigest()
for p in [R/'Python/optimizer.c',R/'Include/internal/pycore_interp_structs.h',R/'Lib/test/test_capi/test_opt.py',R/'Tools/jit/_optimizers.py']:
 manifest['files'][str(p.relative_to(R))]=hashlib.sha256(p.read_bytes()).hexdigest()
(O/'build-identities.json').write_text(json.dumps(manifest,indent=2)+'\n')
