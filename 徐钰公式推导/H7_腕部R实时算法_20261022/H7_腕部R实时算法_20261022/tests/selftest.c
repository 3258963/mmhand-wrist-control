#include "wrist_r.h"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <assert.h>
#include <math.h>
#include <stdio.h>

static void all_nan(const wrist_result_t *r)
{
    unsigned j,i;
    assert(!r->math_valid && !r->geometry_gate_passed);
    for(j=0;j<2u;++j)for(i=0;i<3u;++i)assert(isnan(r->R_m[j][i]));
}
int main(void)
{
    wrist_context_t ctx={0},uninitialized={0};
    wrist_config_t cfg;
    wrist_result_t a,b;
    unsigned j,i;
    assert(sizeof(float)==4u);
    assert(wrist_init(NULL,&wrist_default_config)==WRIST_ERR_ARGUMENT);
    assert(wrist_init(&ctx,NULL)==WRIST_ERR_ARGUMENT);
    assert(wrist_compute_R_rad(NULL,0,0,&a)==WRIST_ERR_ARGUMENT);all_nan(&a);
    assert(wrist_compute_R_rad(&uninitialized,0,0,&a)==WRIST_ERR_NOT_INITIALIZED);all_nan(&a);
    assert(wrist_compute_R_rad(&uninitialized,0,0,NULL)==WRIST_ERR_ARGUMENT);
    assert(wrist_init(&ctx,&wrist_default_config)==WRIST_OK);
    assert(!wrist_status_has_error(wrist_compute_R_rad(&ctx,0,0,&a)));
    assert(a.math_valid && a.rank_2 && a.has_positive_internal_preload && !a.geometry_gate_passed);
    assert(a.status & WRIST_WARN_UNCALIBRATED);assert(a.status & WRIST_WARN_GUARDS_UNSET);
    assert(fabsf(a.R_m[0][1]+0.0220497010f)<2e-7f);
    assert(fabsf(a.R_m[1][0]+0.0581046156f)<2e-7f);
    assert(wrist_compute_R_rad(&ctx,NAN,0,&a)&WRIST_ERR_NONFINITE_INPUT);all_nan(&a);
    assert(wrist_compute_R_rad(&ctx,0,INFINITY,&a)&WRIST_ERR_NONFINITE_INPUT);all_nan(&a);
    assert(wrist_compute_R_deg(&ctx,26,0,&a)&WRIST_ERR_ANGLE_RANGE);all_nan(&a);
    assert(wrist_compute_R_deg(&ctx,0,-26,&a)&WRIST_ERR_ANGLE_RANGE);all_nan(&a);
    assert(!wrist_status_has_error(wrist_compute_R_deg(&ctx,10,20,&a)));
    assert(!wrist_status_has_error(wrist_compute_R_rad(&ctx,0.17453292519943295f,0.3490658503988659f,&b)));
    for(j=0;j<2u;++j)for(i=0;i<3u;++i)assert(fabsf(a.R_m[j][i]-b.R_m[j][i])<1e-7f);
    cfg=wrist_default_config;cfg.encoder_sign[1]=-1.0f;cfg.encoder_zero_rad[0]=0.1f;
    assert(wrist_init(&ctx,&cfg)==WRIST_OK);
    wrist_compute_R_encoder_rad(&ctx,0.1f,-0.2f,&a);wrist_compute_R_rad(&ctx,0.0f,0.2f,&b);
    for(j=0;j<2u;++j)for(i=0;i<3u;++i)assert(fabsf(a.R_m[j][i]-b.R_m[j][i])<1e-7f);
    /* Reinitializing from the context's own copied configuration is safe. */
    assert(wrist_init(&ctx,&ctx.cfg)==WRIST_OK);
    cfg=wrist_default_config;cfg.encoder_sign[0]=0;assert(wrist_init(&ctx,&cfg)==WRIST_ERR_CONFIG);
    cfg=wrist_default_config;cfg.segment[0][0].h_m=NAN;assert(wrist_init(&ctx,&cfg)==WRIST_ERR_CONFIG);
    cfg=wrist_default_config;cfg.guards_confirmed=true;assert(wrist_init(&ctx,&cfg)==WRIST_ERR_CONFIG);
    cfg=wrist_default_config;cfg.calibration_confirmed=true;cfg.guards_confirmed=true;
    for(j=0;j<2u;++j)for(i=0;i<3u;++i)cfg.min_length_guard_m[j][i]=0.002f; /* TEST ONLY */
    assert(wrist_init(&ctx,&cfg)==WRIST_OK);wrist_compute_R_rad(&ctx,0,0,&a);assert(a.geometry_gate_passed);
    /* Caller mutation after init must not alter the copied context. */
    cfg.segment[0][0].u1_m=99;wrist_compute_R_rad(&ctx,0,0,&b);assert(a.R_m[0][0]==b.R_m[0][0]);
    wrist_compute_R_deg(&ctx,0,-25,&a);assert(a.math_valid && (a.status&WRIST_WARN_LOW_PITCH) && !a.geometry_gate_passed);
    wrist_compute_R_deg(&ctx,0,45,&a);assert(a.math_valid && !a.has_positive_internal_preload && !a.geometry_gate_passed);
    cfg=ctx.cfg;cfg.min_length_guard_m[1][0]=0.005f; /* TEST ONLY, not a production recommendation */
    assert(wrist_init(&ctx,&cfg)==WRIST_OK);
    assert(wrist_compute_R_deg(&ctx,0,-25,&a)&WRIST_ERR_SEGMENT_GUARD);all_nan(&a);assert(a.bad_axis==1u && a.bad_cable==0u);
    cfg=wrist_default_config;cfg.segment[0][0]=(wrist_segment_t){0,0,0,0,0};
    assert(wrist_init(&ctx,&cfg)==WRIST_OK);
    assert(wrist_compute_R_rad(&ctx,0,0,&a)&WRIST_ERR_SEGMENT_NUMERICAL);all_nan(&a);
    cfg=wrist_default_config;for(i=0;i<3u;++i)cfg.segment[0][i]=(wrist_segment_t){0,0,0.01f,0,0.01f};
    assert(wrist_init(&ctx,&cfg)==WRIST_OK);wrist_compute_R_rad(&ctx,0,0,&a);
    assert(a.math_valid && !a.rank_2 && !a.has_positive_internal_preload && (a.status&WRIST_WARN_RANK));
    cfg=wrist_default_config;for(i=0;i<3u;++i)cfg.segment[0][i]=cfg.segment[1][i];
    assert(wrist_init(&ctx,&cfg)==WRIST_OK);wrist_compute_R_rad(&ctx,0,0,&a);assert(a.math_valid && !a.rank_2);
    puts("selftest: PASS");return 0;
}
