import './globals.css';
import './insights.css';
import './channels.css';
export const metadata = {title: 'YouTube Automation', description: 'Your local Shorts production dashboard'};
export const viewport = {themeColor: '#0c0c0e', colorScheme: 'dark'};
export default function Layout({children}) {
  return <html lang="en"><body>{children}</body></html>;
}
