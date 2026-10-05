import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { QRCodeSVG } from "qrcode.react";
import {
  BinaryBitmap,
  HybridBinarizer,
  QRCodeReader,
  RGBLuminanceSource,
} from "@zxing/library";
it("the scanner decodes the exact opaque token rendered by the wallet", () => {
  const token = "Yp2z_opaqueRandomToken-01234567890123456789012";
  const { container } = render(
    <QRCodeSVG value={token} size={224} level="M" marginSize={4} />,
  );
  const svg = container.querySelector("svg")!,
    side = Number(svg.getAttribute("viewBox")!.split(" ")[3]),
    scale = 6,
    width = side * scale;
  const pixels = new Uint8ClampedArray(width * width).fill(255);
  const path = svg.querySelector('path[fill="#000000"]')!.getAttribute("d")!;
  for (const m of path.matchAll(/M(\d+)[ ,](\d+)\s*h(\d+)v1H\d+z/g)) {
    const x = Number(m[1]),
      y = Number(m[2]),
      run = Number(m[3]);
    for (let dy = 0; dy < scale; dy++)
      for (let dx = 0; dx < run * scale; dx++)
        pixels[(y * scale + dy) * width + x * scale + dx] = 0;
  }
  const decoded = new QRCodeReader().decode(
    new BinaryBitmap(
      new HybridBinarizer(new RGBLuminanceSource(pixels, width, width)),
    ),
  );
  expect(decoded.getText()).toBe(token);
});
