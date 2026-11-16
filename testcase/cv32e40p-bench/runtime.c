// Minimal integer-only libc surface for the unchanged upstream CoreMark sources.
#include <stdarg.h>
#include <stddef.h>

void *memset(void *p, int c, size_t n) {
    unsigned char *q = p;
    for (size_t i = 0; i < n; ++i) q[i] = (unsigned char)c;
    return p;
}
void *memcpy(void *p, const void *s, size_t n) {
    unsigned char *q = p;
    const unsigned char *r = s;
    for (size_t i = 0; i < n; ++i) q[i] = r[i];
    return p;
}
int puts(const char *s);
int putchar(int c) {
    *(volatile unsigned *)0x10000000 = (unsigned char)c;
    return (unsigned char)c;
}
int puts(const char *s) {
    int n = 0;
    while (*s) { putchar(*s++); ++n; }
    putchar('\n');
    return n + 1;
}
static int number(unsigned v, unsigned base, int width, int pad) {
    char digits[32]; int n = 0, count = 0;
    do { digits[n++] = "0123456789abcdef"[v % base]; v /= base; } while (v);
    while (width-- > n) { putchar(pad); ++count; }
    count += n;
    while (n) putchar(digits[--n]);
    return count;
}
int printf(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt); int count = 0;
    while (*fmt) {
        if (*fmt++ != '%') { putchar(fmt[-1]); ++count; continue; }
        int pad = ' ', width = 0;
        if (*fmt == '0') { pad = '0'; ++fmt; }
        while (*fmt >= '0' && *fmt <= '9') width = width * 10 + *fmt++ - '0';
        if (*fmt == 'l') ++fmt; // long and int are both 32 bits in ILP32.
        switch (*fmt++) {
        case 's': { const char *s = va_arg(ap, const char *); while (*s) { putchar(*s++); ++count; } break; }
        case 'c': putchar(va_arg(ap, int)); ++count; break;
        case '%': putchar('%'); ++count; break;
        case 'd': { int v = va_arg(ap, int); unsigned u = (unsigned)v;
                    if (v < 0) { putchar('-'); ++count; u = 0u - u; }
                    count += number(u, 10, width, pad); break; }
        case 'u': count += number(va_arg(ap, unsigned), 10, width, pad); break;
        case 'x': count += number(va_arg(ap, unsigned), 16, width, pad); break;
        default: *(volatile unsigned *)0x20000004 = 99; for (;;) {} // reject unsupported formatting
        }
    }
    va_end(ap); return count;
}
