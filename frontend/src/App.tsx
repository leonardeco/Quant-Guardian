import { Navigate, Route, Routes } from "react-router-dom";
import { useToken } from "./api";
import { Forgot, Login, Register, Reset } from "./auth";
import { Copies } from "./copies";
import { Accounts, Desk, Overview, RiskPage, Strategies, Trades } from "./desk";

function Guard() {
  const token = useToken();
  if (!token) return <Navigate to="/login" replace />;
  return <Desk />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/registro" element={<Register />} />
      <Route path="/recuperar" element={<Forgot />} />
      <Route path="/restablecer" element={<Reset />} />
      <Route element={<Guard />}>
        <Route index element={<Overview />} />
        <Route path="cuentas" element={<Accounts />} />
        <Route path="riesgo" element={<RiskPage />} />
        <Route path="estrategias" element={<Strategies />} />
        <Route path="operaciones" element={<Trades />} />
        <Route path="copias" element={<Copies />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
