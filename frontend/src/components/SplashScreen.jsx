import logo from '../assets/bazhi-logo.svg';
export default function SplashScreen() {
  return <div className="min-h-screen flex flex-col gap-4 items-center justify-center bg-gray-50" role="status" aria-label="Carregando Bazhi">
    <img src={logo} alt="Bazhi" className="w-20 h-20 animate-pulse motion-reduce:animate-none" />
    <span className="text-xl font-semibold text-gray-900">Bazhi</span>
  </div>;
}
