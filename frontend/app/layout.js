import './globals.css';

export const metadata = {
  title: 'IBVAP Dashboard',
  description: 'Intelligent Border Video Analytics Platform — operator dashboard',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
