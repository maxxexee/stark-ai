import { QRCodeSVG } from "qrcode.react";

/**
 * Encodes just the address, dark on white with a quiet zone: scanners misread light-on-dark codes.
 */
export function AddressQrCode({ address }: { address: string }) {
  return (
    <div className="self-center rounded-lg border border-border bg-white p-3">
      <QRCodeSVG value={address} size={176} marginSize={2} title="Scan to fill in the address" />
    </div>
  );
}
