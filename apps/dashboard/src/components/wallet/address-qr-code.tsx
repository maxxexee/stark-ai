import { QRCodeSVG } from "qrcode.react";

/** Just the address, so any wallet's scanner reads it. Dark on white with a quiet zone: scanners
 * misread light-on-dark codes. */
export function AddressQrCode({ address }: { address: string }) {
  return (
    <div className="self-center rounded-xl bg-white p-3">
      <QRCodeSVG value={address} size={176} marginSize={2} title="Scan to fill in the address" />
    </div>
  );
}
