import { useCallback, useState } from "react";

import Assistant from "./pages/Assistant.jsx";
import Login from "./pages/Login.jsx";
import { clearToken, getToken, setToken } from "./lib/api.js";

export default function App() {
  const [token, setTokenState] = useState(() => getToken());

  const handleLogin = useCallback((value) => {
    setToken(value);
    setTokenState(value);
  }, []);

  const handleLogout = useCallback(() => {
    clearToken();
    setTokenState("");
  }, []);

  if (!token) {
    return <Login onLogin={handleLogin} />;
  }
  return <Assistant token={token} onLogout={handleLogout} />;
}
