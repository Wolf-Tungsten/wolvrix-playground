#include <stdint.h>
int puts(const char *);
static volatile uint32_t words[8];
int main(void) {
    words[0] = 0x12345678;
    volatile unsigned char *b = (volatile unsigned char *)words;
    b[0] = 0xaa; b[3] = 0xbb;
    ((volatile uint16_t *)words)[1] = 0xccdd;
    if (words[0] != 0xccdd56aa) return 1;
    for (unsigned i = 1; i < 8; ++i) words[i] = words[i-1] ^ (0x1020304u * i);
    uint32_t v = 0xccdd56aa;
    for (unsigned i = 1; i < 8; ++i) { v ^= 0x1020304u * i; if (words[i] != v) return 2; }
    puts("SMOKE PASS");
    return 0;
}
