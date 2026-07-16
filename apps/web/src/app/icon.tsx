import { ImageResponse } from "next/og";

export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        borderRadius: "50%",
        color: "#b83a3a",
        background: "#ffffff",
        border: "2px solid #b83a3a",
        fontSize: 20,
        fontWeight: 700,
      }}
    >
      选
    </div>,
    size,
  );
}
