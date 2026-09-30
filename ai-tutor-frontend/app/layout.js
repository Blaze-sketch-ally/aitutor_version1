import "./globals.css";
import { AuthProvider } from "../lib/AuthContext";

export const metadata = {
  title: "AI Tutor",
  description: "Your research, notes and quiz companion.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
