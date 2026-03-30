import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import { AppShell } from "./components/AppShell";
import { ApiTokensPage } from "./pages/ApiTokensPage";
import { CreateServicePage } from "./pages/CreateServicePage";
import { LoginPage } from "./pages/LoginPage";
import { ServiceInfoPage } from "./pages/ServiceInfoPage";
import { ServiceViewPage } from "./pages/ServiceViewPage";

function ProtectedApp() {
  const { isReady, user } = useAuth();
  if (!isReady) {
    return null;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return (
    <AppShell>
      <Routes>
        <Route path="/services" element={<ServiceViewPage />} />
        <Route path="/services/new" element={<CreateServicePage />} />
        <Route path="/services/:serviceId" element={<ServiceInfoPage />} />
        <Route path="/tokens" element={<ApiTokensPage />} />
        <Route path="*" element={<Navigate to="/services" replace />} />
      </Routes>
    </AppShell>
  );
}

function AppRoutes() {
  const { user } = useAuth();
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/services" replace /> : <LoginPage />} />
      <Route path="/*" element={<ProtectedApp />} />
    </Routes>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
