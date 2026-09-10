import { loadFont } from "@remotion/google-fonts/Geist";
import { loadFont as loadDisplay } from "@remotion/google-fonts/Inter";

// Geist is what clipforgee.app itself is set in, so the ad and the product
// read as one thing.
export const { fontFamily } = loadFont("normal", {
  weights: ["400", "500", "600", "700", "800", "900"],
  subsets: ["latin"],
});

// The hook is set in Inter Black. Monument Extended and Clash Display are
// not on Google Fonts, and shipping a licensed face into the repo is not
// mine to decide, so this is the third of the three you named.
export const { fontFamily: displayFont } = loadDisplay("normal", {
  weights: ["900"],
  subsets: ["latin"],
});

export const BACKGROUND = "#0D0D0E";
// The lit centre of the backdrop, so the frame is never a flat fill.
export const BACKGROUND_CORE = "#1A1A1E";
export const ACCENT = "#FF5B22";
export const UI_GREY = "#1A1A1E";
// The phone bezel, a touch lighter than the UI grey so the edge reads against
// the background rather than dissolving into it.
export const PHONE_BEZEL = "#1E1E24";
export const TEXT = "#FFFFFF";

// Sampled straight out of public/studio.png so the live button we draw over
// the screenshot is indistinguishable from the baked one underneath it.
export const BUTTON_FILL = "#E2603A";
export const BUTTON_LABEL = "#141014";
export const PANEL_BG = "#0E0E11";

// The Publish now button and the four status rows, as fractions of the
// captured dashboard (public/studio.png, 1460x700). Everything that has to
// land on the button — the cursor, the click ripple, the camera's flight
// path through it — is positioned from these, inside the same 3D plane, so
// it stays glued to the pixel it points at however the plane is moving.
export const BUTTON_RECT = {
  left: 0.1832,
  top: 0.2814,
  width: 0.1027,
  height: 0.0693,
};

export const PUBLISH_BUTTON = {
  x: BUTTON_RECT.left + BUTTON_RECT.width / 2,
  y: BUTTON_RECT.top + BUTTON_RECT.height / 2,
};

export const STATUS_ROWS = [
  { top: 0.4586 },
  { top: 0.5443 },
  { top: 0.6443 },
  { top: 0.7443 },
];

export const STATUS_ROW = { left: 0.1836, width: 0.4171, height: 0.0743 };

// The dashboard plane's own coordinate space, matching the crop's 1460x700.
export const PLANE_WIDTH = 1720;
export const PLANE_HEIGHT = 825;

// The isometric angle the dashboard holds for the whole of its screen time.
export const PLANE_PERSPECTIVE = 1400;
export const PLANE_TILT = "16deg";
export const PLANE_ROLL = "-2deg";

// The brief puts the Publish now button at "approx left: 26%, top: 31%".
// Measured off the screenshot it is 23.5% / 31.6%, and the cursor, the
// shockwave and the transform origin of the dive all read from here so they
// hit the button itself rather than a spot near it.
export const BUTTON_ORIGIN =
  (PUBLISH_BUTTON.x * 100).toFixed(1) +
  "% " +
  (PUBLISH_BUTTON.y * 100).toFixed(1) +
  "%";
