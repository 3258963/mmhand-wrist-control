"""Regenerate static SI geometry from CAD point/axis data. Standard library only."""
import hashlib,json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'data/geometry_source.json'
p=json.loads(SOURCE.read_text(encoding='utf-8'))
if p['units']['coordinates']!='m' or p['units']['angles']!='rad':
 raise ValueError('Source geometry must use metres and radians; do not relabel millimetre coordinates')
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
def sub(a,b):return [x-y for x,y in zip(a,b)]
def norm(a):return math.sqrt(dot(a,a))
def normalized(a):
 n=norm(a)
 if not math.isfinite(n) or n<1e-12:raise ValueError('Degenerate direction')
 return [v/n for v in a]
def literal(v):return f'{v:.9e}f'
coords={v['id']:v for v in p['points']}
if len(coords)!=24:raise ValueError('This separable topology requires exactly the specified 24 points')
segments=[];derived=[]
for axis,axisname,orders,reference in [('roll','roll',(4,5),[1.,0.,0.]),('pitch','pitch_zero',(6,7),[0.,1.,0.])]:
 ax=p['axes'][axisname];a=normalized(ax['direction_world']);origin=ax['origin_world_m']
 # Reference vector is arbitrary; its projection and cross product define a right-handed plane.
 ref=[reference[i]-dot(reference,a)*a[i] for i in range(3)]
 if norm(ref)<1e-8:
  reference=[0.,0.,1.];ref=[reference[i]-dot(reference,a)*a[i] for i in range(3)]
 e1=normalized(ref);e2=cross(a,e1);row=[]
 for c in (1,2,3):
  for order in range(1,9):
   marker=coords[f'C{c}-P{order:02d}'];expected='base' if order<=4 else 'roll_link' if order<=6 else 'palm'
   if marker['body']!=expected:raise ValueError('Topology changed: use the general cable Jacobian instead')
  A=coords[f'C{c}-P{orders[0]:02d}']['zero_world_m'];B=coords[f'C{c}-P{orders[1]:02d}']['zero_world_m']
  u=sub(A,origin);v=sub(B,origin)
  values=[dot(u,e1),dot(u,e2),dot(v,e1),dot(v,e2),dot(sub(v,u),a)]
  if not all(math.isfinite(x) for x in values):raise ValueError('Invalid geometry')
  row.append(values)
  alpha=dot(u,u)+dot(v,v)-2*dot(a,u)*dot(a,v)
  beta=-2*(dot(u,v)-dot(a,u)*dot(a,v));gamma=-2*dot(u,cross(a,v))
  derived.append({'axis':axis,'cable':f'C{c}','plane_coefficients_m':values,'alpha_beta_gamma_m2':[alpha,beta,gamma]})
 segments.append(row)
source_hash=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
code='''/* Auto-generated from data/geometry_source.json; do not edit constants by hand.
 * SHA256: '''+source_hash+'''
 * C2/C3 P03/P04 already corrected. NOT hardware-calibrated.
 */
#include "wrist_r.h"
const wrist_config_t wrist_default_config = {
    .segment = {
'''
for row in segments:
 code+='        {\n'+''.join('            { '+', '.join(literal(v) for v in values)+' },\n' for values in row)+'        },\n'
code+='''    },
    .angle_min_rad = { -4.363323130e-01f, -4.363323130e-01f },
    .angle_max_rad = {  4.363323130e-01f,  7.853981634e-01f },
    .numerical_min_length_m = 1.0e-8f,
    .min_length_guard_m = { {0.0f,0.0f,0.0f}, {0.0f,0.0f,0.0f} },
    .calibration_confirmed = false,
    .guards_confirmed = false,
    .encoder_sign = { 1.0f, 1.0f },
    .encoder_zero_rad = { 0.0f, 0.0f },
    .relative_rank_epsilon = 1.0e-6f,
    .positive_null_epsilon = 1.0e-6f,
    .low_pitch_warning_enabled = true,
    .low_pitch_warning_max_rad = -4.188790205e-01f
};
'''
low=[math.radians(p['ranges_deg'][axis][0]) for axis in ('roll','pitch')]
high=[math.radians(p['ranges_deg'][axis][1]) for axis in ('roll','pitch')]
if not all(math.isfinite(x) for x in low+high) or any(a>=b for a,b in zip(low,high)):
 raise ValueError('Invalid angle ranges')
code=code.replace('.angle_min_rad = { -4.363323130e-01f, -4.363323130e-01f }',
                  '.angle_min_rad = { '+', '.join(literal(x) for x in low)+' }')
code=code.replace('.angle_max_rad = {  4.363323130e-01f,  7.853981634e-01f }',
                  '.angle_max_rad = { '+', '.join(literal(x) for x in high)+' }')
(ROOT/'src/wrist_default_model.c').write_text(code,encoding='utf-8')
(ROOT/'data/derived_constants.json').write_text(json.dumps({'source_sha256':source_hash,'segments':derived},ensure_ascii=False,indent=2),encoding='utf-8')
print('Generated src/wrist_default_model.c, source SHA256='+source_hash)
