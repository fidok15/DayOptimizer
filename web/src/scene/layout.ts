// Vertical composition of the scene, as fractions of the viewport height H.
//
//   0 ............ sky (sun/moon, stars, clouds, birds)
//   GROUND ....... far river bank: every building stands on this line
//   WATER_TOP .... river starts (below a thin bank/promenade strip)
//   WATER_BOTTOM . river ends, near-bank park begins
//   1 ............ bottom edge (park foreground)

export const GROUND = 0.74;
export const WATER_TOP = 0.765;
export const WATER_BOTTOM = 0.9;

/** Tallest roof line allowed (fraction of H from the top), keeps a band of sky. */
export const MAX_TOP = 0.1;
