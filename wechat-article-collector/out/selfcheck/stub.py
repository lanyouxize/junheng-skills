import sys, os
cfile, fails, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
n = int(open(cfile).read()) if os.path.exists(cfile) else 0
if n < fails:
    open(cfile,'w').write(str(n+1)); sys.exit(3)
open(cfile,'w').write(str(n+1)); open(out,'w').write('{"x":1}\n'); sys.exit(0)
