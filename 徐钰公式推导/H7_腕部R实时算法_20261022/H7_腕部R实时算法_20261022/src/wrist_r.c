#include "wrist_r.h"
#include <math.h>
#include <stddef.h>
#include <string.h>

#define WRIST_INITIALIZED_TAG UINT32_C(0x57525231)
#define WRIST_DEG_TO_RAD_F 0.01745329251994329577f

/* Compile with strict floating-point semantics: NaN/Inf checks are required. */
static void reset_result(wrist_result_t *out)
{
    unsigned j, i;
    memset(out, 0, sizeof(*out));
    for (j=0; j<WRIST_AXES; ++j) {
        out->physical_angle_rad[j]=NAN;
        for (i=0; i<WRIST_CABLES; ++i) {
            out->R_m[j][i]=NAN;
            out->segment_length_m[j][i]=NAN;
        }
    }
    for (i=0; i<WRIST_CABLES; ++i) out->positive_null_unit[i]=NAN;
    out->condition_2=INFINITY;
    out->bad_axis=UINT8_C(0xff);
    out->bad_cable=UINT8_C(0xff);
}

static wrist_status_t fail_result(wrist_result_t *out, wrist_status_t status,
                                  unsigned axis, unsigned cable)
{
    /* Never leave a partially computed or stale R marked as usable. */
    reset_result(out);
    out->status=status;
    out->bad_axis=(uint8_t)axis;
    out->bad_cable=(uint8_t)cable;
    return status;
}

bool wrist_status_has_error(wrist_status_t status)
{
    return (status & WRIST_ERROR_MASK) != 0u;
}

wrist_status_t wrist_init(wrist_context_t *ctx, const wrist_config_t *cfg)
{
    wrist_config_t config_copy;
    unsigned j, i;
    if (ctx == NULL) return WRIST_ERR_ARGUMENT;
    if (cfg == NULL) { memset(ctx,0,sizeof(*ctx)); return WRIST_ERR_ARGUMENT; }
    config_copy=*cfg;
    memset(ctx, 0, sizeof(*ctx));
    cfg=&config_copy;
    if (!isfinite(cfg->numerical_min_length_m) ||
        cfg->numerical_min_length_m <= 0.0f ||
        !isfinite(cfg->relative_rank_epsilon) ||
        cfg->relative_rank_epsilon <= 0.0f || cfg->relative_rank_epsilon >= 1.0f ||
        !isfinite(cfg->positive_null_epsilon) ||
        cfg->positive_null_epsilon < 0.0f || cfg->positive_null_epsilon >= 0.5f ||
        !isfinite(cfg->low_pitch_warning_max_rad)) return WRIST_ERR_CONFIG;
    for (j=0; j<WRIST_AXES; ++j) {
        if (!isfinite(cfg->angle_min_rad[j]) || !isfinite(cfg->angle_max_rad[j]) ||
            cfg->angle_min_rad[j] >= cfg->angle_max_rad[j] ||
            !isfinite(cfg->encoder_zero_rad[j]) ||
            (cfg->encoder_sign[j] != 1.0f && cfg->encoder_sign[j] != -1.0f))
            return WRIST_ERR_CONFIG;
        for (i=0; i<WRIST_CABLES; ++i) {
            const wrist_segment_t *g=&cfg->segment[j][i];
            float guard=cfg->min_length_guard_m[j][i];
            if (!isfinite(g->u1_m) || !isfinite(g->u2_m) ||
                !isfinite(g->v1_m) || !isfinite(g->v2_m) || !isfinite(g->h_m) ||
                !isfinite(guard) || guard < 0.0f ||
                (cfg->guards_confirmed && guard <= cfg->numerical_min_length_m))
                return WRIST_ERR_CONFIG;
        }
    }
    ctx->cfg=*cfg;
    ctx->initialized_tag=WRIST_INITIALIZED_TAG;
    return WRIST_OK;
}

static void analyze_matrix(wrist_result_t *out, const wrist_config_t *cfg)
{
    float nr, np, a[3], b[3], w[3], n, ab, aa, bb, disc, largest, smallest;
    unsigned i;
    nr=sqrtf(out->R_m[0][0]*out->R_m[0][0]+out->R_m[0][1]*out->R_m[0][1]+out->R_m[0][2]*out->R_m[0][2]);
    np=sqrtf(out->R_m[1][0]*out->R_m[1][0]+out->R_m[1][1]*out->R_m[1][1]+out->R_m[1][2]*out->R_m[1][2]);
    if (!isfinite(nr) || !isfinite(np) || nr <= 0.0f || np <= 0.0f) {
        out->status |= WRIST_WARN_RANK | WRIST_WARN_NO_POSITIVE_NULL;
        return;
    }
    for (i=0; i<3u; ++i) { a[i]=out->R_m[0][i]/nr; b[i]=out->R_m[1][i]/np; }
    w[0]=a[1]*b[2]-a[2]*b[1];
    w[1]=a[2]*b[0]-a[0]*b[2];
    w[2]=a[0]*b[1]-a[1]*b[0];
    n=sqrtf(w[0]*w[0]+w[1]*w[1]+w[2]*w[2]);
    if (!isfinite(n) || n <= cfg->relative_rank_epsilon) {
        out->status |= WRIST_WARN_RANK | WRIST_WARN_NO_POSITIVE_NULL;
        return;
    }
    out->rank_2=true;
    if (w[0]+w[1]+w[2] < 0.0f) for (i=0; i<3u; ++i) w[i]=-w[i];
    for (i=0; i<3u; ++i) out->positive_null_unit[i]=w[i]/n;
    out->has_positive_internal_preload=
        out->positive_null_unit[0] > cfg->positive_null_epsilon &&
        out->positive_null_unit[1] > cfg->positive_null_epsilon &&
        out->positive_null_unit[2] > cfg->positive_null_epsilon;
    if (!out->has_positive_internal_preload) out->status |= WRIST_WARN_NO_POSITIVE_NULL;
    /* Condition number of the full 2x3 matrix (not normalized rows). */
    aa=nr*nr; bb=np*np;
    ab=out->R_m[0][0]*out->R_m[1][0]+out->R_m[0][1]*out->R_m[1][1]+out->R_m[0][2]*out->R_m[1][2];
    disc=sqrtf((aa-bb)*(aa-bb)+4.0f*ab*ab);
    largest=0.5f*(aa+bb+disc);
    smallest=(aa*bb*n*n)/largest; /* avoids subtracting close eigenvalues */
    if (smallest > 0.0f && isfinite(smallest) && isfinite(largest))
        out->condition_2=sqrtf(largest/smallest);
    if (!isfinite(out->condition_2)) {
        out->rank_2=false;
        out->has_positive_internal_preload=false;
        out->status |= WRIST_WARN_RANK | WRIST_WARN_NO_POSITIVE_NULL;
    }
}

wrist_status_t wrist_compute_R_rad(const wrist_context_t *ctx,
    float roll_rad, float pitch_rad, wrist_result_t *out)
{
    const wrist_config_t *cfg;
    float angles[2], s, c;
    wrist_status_t status=WRIST_OK;
    unsigned j, i;
    if (out == NULL) return WRIST_ERR_ARGUMENT;
    reset_result(out);
    if (ctx == NULL) return fail_result(out, WRIST_ERR_ARGUMENT, 0xffu, 0xffu);
    if (ctx->initialized_tag != WRIST_INITIALIZED_TAG)
        return fail_result(out, WRIST_ERR_NOT_INITIALIZED, 0xffu, 0xffu);
    cfg=&ctx->cfg;
    if (!isfinite(roll_rad) || !isfinite(pitch_rad))
        return fail_result(out, WRIST_ERR_NONFINITE_INPUT, 0xffu, 0xffu);
    angles[0]=roll_rad; angles[1]=pitch_rad;
    for (j=0; j<WRIST_AXES; ++j)
        if (angles[j] < cfg->angle_min_rad[j] || angles[j] > cfg->angle_max_rad[j])
            return fail_result(out, WRIST_ERR_ANGLE_RANGE, j, 0xffu);
    if (!cfg->calibration_confirmed) status |= WRIST_WARN_UNCALIBRATED;
    if (!cfg->guards_confirmed) status |= WRIST_WARN_GUARDS_UNSET;
    if (cfg->low_pitch_warning_enabled && pitch_rad <= cfg->low_pitch_warning_max_rad)
        status |= WRIST_WARN_LOW_PITCH;
    for (j=0; j<WRIST_AXES; ++j) {
        /* sinf/cosf take radians. A library replacement must preserve that API. */
        s=sinf(angles[j]); c=cosf(angles[j]);
        for (i=0; i<WRIST_CABLES; ++i) {
            const wrist_segment_t *g=&cfg->segment[j][i];
            float v1=g->v1_m*c-g->v2_m*s;
            float v2=g->v1_m*s+g->v2_m*c;
            float d1=v1-g->u1_m, d2=v2-g->u2_m;
            float D=d1*d1+d2*d2+g->h_m*g->h_m;
            float length, r;
            if (!isfinite(D) || D <= 0.0f)
                return fail_result(out,status|WRIST_ERR_SEGMENT_NUMERICAL,j,i);
            length=sqrtf(D);
            if (!isfinite(length) || length <= cfg->numerical_min_length_m)
                return fail_result(out,status|WRIST_ERR_SEGMENT_NUMERICAL,j,i);
            /* Equivalent to (beta*sin-gamma*cos)/(2*sqrt(D)); stable near short segments. */
            r=(d1*v2-d2*v1)/length;
            if (!isfinite(r)) return fail_result(out,status|WRIST_ERR_NONFINITE_RESULT,j,i);
            if (cfg->min_length_guard_m[j][i] > 0.0f && length < cfg->min_length_guard_m[j][i])
                return fail_result(out,status|WRIST_ERR_SEGMENT_GUARD,j,i);
            out->R_m[j][i]=r;
            out->segment_length_m[j][i]=length;
        }
    }
    out->physical_angle_rad[0]=roll_rad;
    out->physical_angle_rad[1]=pitch_rad;
    out->math_valid=true;
    out->status=status;
    analyze_matrix(out,cfg);
    out->geometry_gate_passed=cfg->calibration_confirmed && cfg->guards_confirmed &&
        out->math_valid && out->rank_2 && out->has_positive_internal_preload &&
        (out->status & WRIST_WARN_LOW_PITCH)==0u;
    return out->status;
}

wrist_status_t wrist_compute_R_deg(const wrist_context_t *ctx,
    float roll_deg, float pitch_deg, wrist_result_t *out)
{
    return wrist_compute_R_rad(ctx,roll_deg*WRIST_DEG_TO_RAD_F,pitch_deg*WRIST_DEG_TO_RAD_F,out);
}

wrist_status_t wrist_compute_R_encoder_rad(const wrist_context_t *ctx,
    float roll_encoder_rad, float pitch_encoder_rad, wrist_result_t *out)
{
    float r, p;
    if (ctx == NULL || ctx->initialized_tag != WRIST_INITIALIZED_TAG)
        return wrist_compute_R_rad(ctx,NAN,NAN,out);
    r=ctx->cfg.encoder_sign[0]*(roll_encoder_rad-ctx->cfg.encoder_zero_rad[0]);
    p=ctx->cfg.encoder_sign[1]*(pitch_encoder_rad-ctx->cfg.encoder_zero_rad[1]);
    return wrist_compute_R_rad(ctx,r,p,out);
}
