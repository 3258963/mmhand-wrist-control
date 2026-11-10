#include "wrist_r.h"
#include <stdio.h>
int main(void)
{
    wrist_context_t ctx={0};
    wrist_result_t result;
    float r,p;
    unsigned j,i;
    if (wrist_init(&ctx,&wrist_default_config)!=WRIST_OK) return 2;
    while (scanf("%f %f",&r,&p)==2) {
        wrist_status_t status=wrist_compute_R_rad(&ctx,r,p,&result);
        printf("%u,%u,%u,%u,%u",(unsigned)status,(unsigned)result.math_valid,
          (unsigned)result.rank_2,(unsigned)result.has_positive_internal_preload,(unsigned)result.geometry_gate_passed);
        for(j=0;j<2u;++j)for(i=0;i<3u;++i)printf(",%.9g",(double)result.R_m[j][i]);
        for(j=0;j<2u;++j)for(i=0;i<3u;++i)printf(",%.9g",(double)result.segment_length_m[j][i]);
        printf(",%.9g\n",(double)result.condition_2);
    }
    return 0;
}
