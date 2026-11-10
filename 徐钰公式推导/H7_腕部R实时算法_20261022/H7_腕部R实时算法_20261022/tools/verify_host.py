"""Build/test portable C using GCC, Clang, or Zig cc; no numpy, no hardware."""
import argparse,csv,hashlib,json,math,os,random,shutil,struct,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def sub(a,b):return [x-y for x,y in zip(a,b)]
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def norm(a):return math.sqrt(dot(a,a))
def rotate(v,a,t):
 c=math.cos(t);s=math.sin(t);av=cross(a,v);k=dot(a,v)*(1-c)
 return [c*v[i]+s*av[i]+a[i]*k for i in range(3)]
def f32(v):return struct.unpack('f',struct.pack('f',v))[0]

def reference(p,q):
    # Independent double-precision 3D axis-vector torque route.
    # Does not use production plane coefficients or the C implementation.
    pts={v['id']:v['zero_world_m'] for v in p['points']};R=[];length=[]
    for j,(name,indices) in enumerate([('roll',(4,5)),('pitch_zero',(6,7))]):
        axis=p['axes'][name]['direction_world'];n=norm(axis);axis=[x/n for x in axis];o=p['axes'][name]['origin_world_m']
        rr=[];ss=[]
        for c in (1,2,3):
            u=sub(pts[f'C{c}-P{indices[0]:02d}'],o);v=sub(pts[f'C{c}-P{indices[1]:02d}'],o)
            v=rotate(v,axis,q[j]);d=sub(v,u);s=norm(d)
            rr.append(dot(u,cross(axis,v))/s);ss.append(s)
        R.append(rr);length.append(ss)
    a,b=R;nn=norm(cross(a,b));w=[x/nn for x in cross(a,b)]
    positive=all(x>1e-6 for x in w) or all(x< -1e-6 for x in w)
    return R,length,positive

def main():
    if not __debug__:raise SystemExit('Run Python without -O: verification assertions must remain enabled')
    parser=argparse.ArgumentParser()
    parser.add_argument('--cc',help='GCC or Clang executable path')
    parser.add_argument('--zig',help='Zig executable path; invokes zig cc')
    parser.add_argument('--skip-cad-comparison',action='store_true',help='Explicitly omit old CAD references after a geometry change')
    args=parser.parse_args()
    if args.zig:compiler=[str(Path(args.zig).resolve()),'cc']
    elif args.cc:compiler=[args.cc]
    else:
        cc=shutil.which('gcc') or shutil.which('clang') or shutil.which('cc')
        if not cc:raise SystemExit('GCC/Clang not found. Supply --cc PATH or --zig PATH.')
        compiler=[cc]
    build=ROOT/'.build';build.mkdir(exist_ok=True)
    suffix='.exe' if os.name=='nt' else ''
    driver=build/('host_driver'+suffix);selftest=build/('selftest'+suffix)
    flags=['-std=c99','-O2','-UNDEBUG','-Wall','-Wextra','-Werror','-fno-fast-math','-ffp-contract=off','-I',str(ROOT/'src')]
    sources=[str(ROOT/'src/wrist_r.c'),str(ROOT/'src/wrist_default_model.c'),str(ROOT/'examples/h7_integration.c')]
    commands=[]
    for source,exe in [('tests/host_driver.c',driver),('tests/selftest.c',selftest)]:
        command=compiler+flags+sources+[str(ROOT/source),'-lm','-o',str(exe)]
        subprocess.run(command,check=True,cwd=ROOT);commands.append(command)
    unit=subprocess.run([str(selftest)],capture_output=True,text=True,check=True)
    geometry_path=ROOT/'data/geometry_source.json';p=json.loads(geometry_path.read_text(encoding='utf-8'))
    source_hash=hashlib.sha256(geometry_path.read_bytes()).hexdigest()
    manifest=json.loads((ROOT/'data/reference_manifest.json').read_text(encoding='utf-8'))
    if not args.skip_cad_comparison and source_hash!=manifest['geometry_sha256']:
        raise SystemExit('Geometry changed: old CAD R table is no longer authoritative. Update independent CAD references or explicitly --skip-cad-comparison.')
    if not args.skip_cad_comparison and hashlib.sha256((ROOT/'data/R_grid_corrected.csv').read_bytes()).hexdigest()!=manifest['cad_R_sha256']:
        raise SystemExit('CAD reference file hash mismatch')
    grid=list(csv.DictReader((ROOT/'data/R_grid_corrected.csv').open(encoding='utf-8-sig')))
    cases=[(math.radians(float(r['yaw_deg'])),math.radians(float(r['pitch_deg']))) for r in grid]
    rng=random.Random(20261022)
    cases += [(math.radians(rng.uniform(-25,25)),math.radians(rng.uniform(-25,45))) for _ in range(5000)]
    cases += [(math.radians(r),math.radians(-25+2*k/200)) for r in (-25,0,25) for k in range(201)]
    cases += [(math.radians(r),math.radians(pitch)) for r in (-25,-18.4882306856,0,15.149528812,25) for pitch in (-25,-24,0,33.8304980862,45)]
    data=''.join(f'{r:.17g} {p:.17g}\n' for r,p in cases)
    run=subprocess.run([str(driver)],input=data,capture_output=True,text=True,check=True)
    lines=run.stdout.splitlines();assert len(lines)==len(cases)
    maximum=[[0.]*3 for _ in range(2)];squares=[[0.]*3 for _ in range(2)]
    len_max=angle_inclusive_max=cad_max=0.;flag_matches=0;no_positive=0;gate_count=0;worst=None
    for index,((r,pitch),line) in enumerate(zip(cases,lines)):
        values=line.split(',');assert len(values)==18,line
        status,valid,rank,positive,gate=map(int,values[:5]);assert status&0xff==0 and valid==1 and rank==1,(index,line)
        R=[[float(values[5+3*j+i]) for i in range(3)] for j in range(2)]
        lengths=[[float(values[11+3*j+i]) for i in range(3)] for j in range(2)]
        q=(f32(r),f32(pitch));ref,ref_lengths,ref_positive=reference(p,q)
        desired,_,_=reference(p,(r,pitch));gate_count+=gate
        for j in range(2):
            for i in range(3):
                error=abs(R[j][i]-ref[j][i])*1000
                if error>maximum[j][i]:
                    maximum[j][i]=error
                    if worst is None or error>worst['error_mm']:worst={'case':index,'roll_deg':math.degrees(r),'pitch_deg':math.degrees(pitch),'axis':j,'cable':i+1,'error_mm':error}
                squares[j][i]+=error*error
                len_max=max(len_max,abs(lengths[j][i]-ref_lengths[j][i])*1000)
                angle_inclusive_max=max(angle_inclusive_max,abs(R[j][i]-desired[j][i])*1000)
        assert positive==ref_positive,('positive-null mismatch against float-angle double reference',index)
        if index<len(grid) and not args.skip_cad_comparison:
            expected=grid[index]['positive_null']=='True';flag_matches+=positive==expected;no_positive+=not positive
            for j,axis in enumerate(('yaw','pitch')):
                for i in range(3):cad_max=max(cad_max,abs(R[j][i]-float(grid[index][f'R_{axis}_C{i+1}_m']))*1000)
    # Acceptance values are software numerical thresholds, NOT hardware accuracy claims.
    assert max(map(max,maximum))<0.001,maximum
    assert len_max<0.0001,len_max
    assert gate_count==0,'Uncalibrated default model must never pass the geometry gate'
    if not args.skip_cad_comparison:assert flag_matches==3621 and no_positive==1664,(flag_matches,no_positive)
    report={'scope':'Host-compiled C single precision vs independent double geometry. No H7 timing or hardware accuracy tested.',
        'compiler':compiler,'compile_commands':commands,'compile_flags':flags,
        'geometry_sha256':source_hash,'grid_cases':len(grid),'random_cases':5000,'near_boundary_cases':603,'additional_extrema_cases':25,
        'total_cases':len(cases),'selftest':unit.stdout.strip(),'passed':True,
        'max_abs_float_vs_double_mm_by_element':maximum,
        'rmse_float_vs_double_mm_by_element':[[math.sqrt(x/len(cases)) for x in row] for row in squares],
        'max_segment_length_error_mm':len_max,'max_including_input_float_rounding_mm':angle_inclusive_max,'worst_case':worst,
        'cad_comparison_skipped':args.skip_cad_comparison,'preload_grid_flag_matches':flag_matches,'grid_without_positive_preload':no_positive,
        'max_C_float_vs_CAD_finite_difference_mm':cad_max,'default_geometry_gate_pass_count':gate_count,
        'software_acceptance_limits':{'R_max_abs_mm':0.001,'length_max_abs_mm':0.0001},
        'not_validated':['Actual STM32H7 project build/link','DWT execution cycles and worst-case ISR latency','Engineering segment guards','Mechanical zero offsets and actual geometry','Real contact/friction/elasticity and bounded tension/torque capacity']}
    (ROOT/'主机验证报告.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('compile_commands','compile_flags')},ensure_ascii=True,indent=2))
if __name__=='__main__':main()
