/* Object-file compilation only. Task code is never linked or executed. */
#include <string.h>
#include "libtcc.h"
int openci_compile(const char *source) {
    if (!source || strlen(source) > 131072) return -1;
    TCCState *state = tcc_new();
    if (!state) return -2;
    tcc_set_options(state, "-nostdinc -nostdlib");
    int result = tcc_set_output_type(state, TCC_OUTPUT_OBJ);
    if (!result) result = tcc_compile_string(state, source);
    if (!result) result = tcc_output_file(state, "/output.o");
    tcc_delete(state);
    return result;
}
