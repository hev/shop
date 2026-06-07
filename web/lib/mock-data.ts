import type { Product } from "./types";

const img = (seed: string) => `https://picsum.photos/seed/${seed}/900/900`;

export const PRODUCTS: Product[] = [
  {
    asin: "B07XYAA111",
    title: "Aurora Wireless Over-Ear Headphones",
    description:
      "Studio-grade 40mm drivers, 38-hour battery, and active noise cancellation. Memory-foam earcups in vegan leather.",
    category: "Electronics",
    image_url: img("headphones-aurora"),
    price: 248,
    rating: 4.6,
    rating_count: 12480,
  },
  {
    asin: "B08AAA222B",
    title: "Halcyon Mechanical Keyboard 65%",
    description:
      "Hot-swappable switches, gasket-mounted aluminum chassis, PBT keycaps. Tactile and quiet for long sessions.",
    category: "Electronics",
    image_url: img("keyboard-halcyon"),
    price: 169,
    rating: 4.8,
    rating_count: 3120,
  },
  {
    asin: "B09CAM333C",
    title: "Field Compact Mirrorless Camera",
    description:
      "24MP APS-C sensor, in-body stabilization, and a tactile dial-forward control scheme inspired by classic rangefinders.",
    category: "Electronics",
    image_url: img("camera-field"),
    price: 899,
    rating: 4.7,
    rating_count: 902,
  },
  {
    asin: "B07LMP444D",
    title: "Ember Smart Coffee Mug",
    description:
      "App-controlled temperature, induction charging coaster, holds 10oz at a precise 130°F for up to 90 minutes.",
    category: "Kitchen",
    image_url: img("mug-ember"),
    price: 129,
    rating: 4.3,
    rating_count: 8401,
  },
  {
    asin: "B06ZOR555E",
    title: "Bowery French Press, 8-Cup",
    description:
      "Double-wall borosilicate glass with a brushed-steel cradle and a four-level micro-mesh filter system.",
    category: "Kitchen",
    image_url: img("frenchpress-bowery"),
    price: 64,
    rating: 4.5,
    rating_count: 2210,
  },
  {
    asin: "B05CHE666F",
    title: "Mortar & Pestle, Granite",
    description:
      "Hand-carved unpolished granite. Six-inch diameter, two-pound base. Ideal for spice pastes and herb mashes.",
    category: "Kitchen",
    image_url: img("mortar-granite"),
    price: 39,
    rating: 4.7,
    rating_count: 1503,
  },
  {
    asin: "B04SOF777G",
    title: "Linen Tufted Loveseat",
    description:
      "Solid hardwood frame, hand-tufted Belgian linen, removable cushion covers. Seats two with quiet confidence.",
    category: "Home",
    image_url: img("loveseat-linen"),
    price: 1299,
    rating: 4.4,
    rating_count: 412,
  },
  {
    asin: "B04LAM888H",
    title: "Aperture Brass Floor Lamp",
    description:
      "Solid brass arc, marble base, dimmable warm-LED bulb included. A reading corner in a single object.",
    category: "Home",
    image_url: img("lamp-aperture"),
    price: 329,
    rating: 4.6,
    rating_count: 188,
  },
  {
    asin: "B03RUG999J",
    title: "Atlas Hand-Knotted Wool Rug, 8×10",
    description:
      "Hand-knotted New Zealand wool, vegetable-dyed. Heirloom-grade pile and a low-contrast geometric pattern.",
    category: "Home",
    image_url: img("rug-atlas"),
    price: 1149,
    rating: 4.8,
    rating_count: 76,
  },
  {
    asin: "B02JAK000K",
    title: "Wayfinder Waxed Canvas Jacket",
    description:
      "Made in Maine. Sanforized waxed canvas, blanket-lined yoke, antique brass hardware. Breaks in over years.",
    category: "Apparel",
    image_url: img("jacket-wayfinder"),
    price: 385,
    rating: 4.7,
    rating_count: 1042,
  },
  {
    asin: "B02SHO111L",
    title: "Trail Runner GTX, Volcanic Olive",
    description:
      "Vibram megagrip outsole, Gore-Tex bootie, rock plate. Built for wet roots and granite scrambles.",
    category: "Apparel",
    image_url: img("shoes-trail"),
    price: 175,
    rating: 4.5,
    rating_count: 3318,
  },
  {
    asin: "B02WAT222M",
    title: "Field Diver Automatic Watch",
    description:
      "Swiss Sellita SW200 movement, 200m water resistance, 38mm brushed steel case. Sapphire crystal.",
    category: "Apparel",
    image_url: img("watch-field"),
    price: 520,
    rating: 4.6,
    rating_count: 612,
  },
  {
    asin: "B01BOK333N",
    title: "The Pattern on the Stone — Daniel Hillis",
    description:
      "A short, lucid book on how computers actually work, from logic gates up to learning machines.",
    category: "Books",
    image_url: img("book-stone"),
    price: 14,
    rating: 4.7,
    rating_count: 1820,
  },
  {
    asin: "B01BOK444P",
    title: "Designing Data-Intensive Applications",
    description:
      "Kleppmann's definitive guide to storage, replication, partitioning, and consistency for modern systems.",
    category: "Books",
    image_url: img("book-data"),
    price: 47,
    rating: 4.9,
    rating_count: 9412,
  },
  {
    asin: "B01BOK555Q",
    title: "The Country of the Pointed Firs",
    description:
      "Sarah Orne Jewett's coastal sketches. Slim, perfect, and quietly devastating in the right light.",
    category: "Books",
    image_url: img("book-firs"),
    price: 12,
    rating: 4.5,
    rating_count: 502,
  },
  {
    asin: "B00BAG666R",
    title: "Caldera 40L Roll-Top Backpack",
    description:
      "Recycled X-Pac sailcloth, magnetic roll closure, removable hip belt. Carries a week or a workday.",
    category: "Apparel",
    image_url: img("backpack-caldera"),
    price: 215,
    rating: 4.6,
    rating_count: 1188,
  },
  {
    asin: "B00SUN777S",
    title: "Meridian Polarized Sunglasses",
    description:
      "Bio-acetate frames, CR-39 polarized lenses, hand-finished in Italy. Light, balanced, classic.",
    category: "Apparel",
    image_url: img("sunglasses-meridian"),
    price: 168,
    rating: 4.4,
    rating_count: 730,
  },
  {
    asin: "B00DSK888T",
    title: "Hearth Walnut Standing Desk",
    description:
      "Solid American walnut top, dual-motor steel base, programmable heights. Quiet, fast, square as a billiard.",
    category: "Home",
    image_url: img("desk-hearth"),
    price: 949,
    rating: 4.8,
    rating_count: 244,
  },
  {
    asin: "B00CHA999U",
    title: "Loom Ergonomic Task Chair",
    description:
      "Mesh back with adjustable lumbar, headrest, and 4D arms. Twelve-year warranty out of the box.",
    category: "Home",
    image_url: img("chair-loom"),
    price: 689,
    rating: 4.5,
    rating_count: 1402,
  },
  {
    asin: "B00PAN111V",
    title: "Solstice Carbon-Steel Skillet, 12in",
    description:
      "Hand-hammered carbon steel, pre-seasoned, riveted helper handle. Heats like cast iron, weighs half as much.",
    category: "Kitchen",
    image_url: img("pan-solstice"),
    price: 89,
    rating: 4.8,
    rating_count: 3712,
  },
  {
    asin: "B00KNI222W",
    title: "Edge 8-inch Damascus Chef's Knife",
    description:
      "67-layer VG-10 damascus core, stabilized wood handle, hand-finished 15° edge. Cuts a tomato in its sleep.",
    category: "Kitchen",
    image_url: img("knife-edge"),
    price: 159,
    rating: 4.7,
    rating_count: 2204,
  },
  {
    asin: "B00LAM333X",
    title: "Quill Pendant Light, Brass",
    description:
      "Spun-brass shade, cloth-wrapped cord, low-profile canopy. Sized for a kitchen island or hallway.",
    category: "Home",
    image_url: img("light-quill"),
    price: 219,
    rating: 4.6,
    rating_count: 312,
  },
  {
    asin: "B00SPK444Y",
    title: "Lumen Portable Bluetooth Speaker",
    description:
      "20-hour battery, IPX7, surprisingly large sound from a palm-sized cylinder. Pair two for stereo.",
    category: "Electronics",
    image_url: img("speaker-lumen"),
    price: 119,
    rating: 4.4,
    rating_count: 5402,
  },
  {
    asin: "B00TAB555Z",
    title: "Pocket E-Reader 6.8in",
    description:
      "300ppi e-ink, warm and cool front-lights, waterproof. Reads outside, lasts weeks, holds a library.",
    category: "Electronics",
    image_url: img("ereader-pocket"),
    price: 189,
    rating: 4.5,
    rating_count: 6210,
  },
  {
    asin: "B00WAT666A",
    title: "Stratus Stainless Insulated Bottle, 32oz",
    description:
      "Triple-wall vacuum insulation, leak-proof cap, holds cold 36 hours. Available in eleven matte colors.",
    category: "Kitchen",
    image_url: img("bottle-stratus"),
    price: 42,
    rating: 4.7,
    rating_count: 12420,
  },
  {
    asin: "B00JOU777B",
    title: "Field Notes Notebook, 3-Pack",
    description:
      "48-page memo books, graph-ruled, made in the USA. Fits any back pocket and most ideas.",
    category: "Books",
    image_url: img("notebook-fieldnotes"),
    price: 12,
    rating: 4.8,
    rating_count: 4180,
  },
  {
    asin: "B00PEN888C",
    title: "Astra Brass Fountain Pen, Medium Nib",
    description:
      "Solid brass body, German-made steel nib, converter included. Writes wet and gets better with use.",
    category: "Books",
    image_url: img("pen-astra"),
    price: 88,
    rating: 4.6,
    rating_count: 612,
  },
  {
    asin: "B00CAN999D",
    title: "Hemlock Soy Candle, 9oz",
    description:
      "Hand-poured soy wax with notes of douglas fir, smoke, and cracked black pepper. 60-hour burn.",
    category: "Home",
    image_url: img("candle-hemlock"),
    price: 38,
    rating: 4.7,
    rating_count: 2810,
  },
  {
    asin: "B00BLK000E",
    title: "Foundry Cast-Iron Dutch Oven, 6qt",
    description:
      "Enameled cast iron, oven-safe to 500°F, lifetime warranty. Builds a stew in one heavy, beautiful pot.",
    category: "Kitchen",
    image_url: img("dutchoven-foundry"),
    price: 245,
    rating: 4.8,
    rating_count: 3110,
  },
  {
    asin: "B00MIC111F",
    title: "Cardioid Studio Microphone, USB",
    description:
      "24-bit/96kHz capsule, zero-latency headphone monitoring, all-metal yoke. Plug-and-record podcasts and demos.",
    category: "Electronics",
    image_url: img("mic-cardioid"),
    price: 149,
    rating: 4.5,
    rating_count: 4012,
  },
];

export function findByAsin(asin: string): Product | undefined {
  return PRODUCTS.find((p) => p.asin === asin);
}
