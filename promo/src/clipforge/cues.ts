// Every cut in the ad hangs off this file, so retiming the whole thing means
// changing numbers here and nowhere else.
//
// These are the frames from the brief. They are NOT where the track's
// transients are. Spectral-flux onset detection over the first twelve seconds
// put the song at 120bpm — a beat every 30 frames — with hits at:
//
//   1.207s -> 72    1.753s -> 105   2.241s -> 134   3.274s -> 196
//   4.238s -> 254   5.817s -> 349   7.837s -> 470  10.890s -> 653
//
// So `find: 0` fires 72 frames before the first vocal, and `click: 460` lands
// 111 frames after the accent nearest "DO". The measured alternative for each
// is in the comment beside it; swap them in to have the picture cut on the
// audio rather than on the round number.
export const CUE = {
  // Scene 1 — kinetic hook.
  find: 0, //        onset 72
  cut: 35, //        onset 105
  publish: 70, //    onset 134
  barFull: 105,
  hookOut: 120,

  // Scene 2 — phones.
  phonesIn: 120,
  phonesHero: 170,

  // Scene 3 — fly-through.
  flyOut: 270, //    onset 196
  dashboardIn: 270,
  dashboardSettled: 380, // onset 254
  phonesGone: 350,

  // Scene 4 — cursor, ripple, banner.
  cursorIn: 420,
  click: 460, //     onset 349
  banner: 472, //    onset 470
  bannerOut: 578,

  // Scene 5 — push-through.
  pushStart: 630,
  pushEnd: 670,
  voidHold: 720,

  // Scene 6 — end card.
  endCard: 720,
  lockupStill: 750,

  total: 900,
} as const;
