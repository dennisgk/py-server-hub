import { Container, Nav, Navbar, NavDropdown } from "react-bootstrap";
import { Link, useLocation, useNavigate } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "../auth";

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const isActive = (href: string) =>
    location.pathname === href || (href !== "/services" && location.pathname.startsWith(`${href}/`));

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <>
      <Navbar bg="dark" variant="dark" expand="lg" className="border-bottom border-secondary-subtle">
        <Container fluid="lg">
          <Navbar.Brand as={Link} to="/services">
            Py Server Hub
          </Navbar.Brand>
          <Navbar.Toggle aria-controls="psh-nav" />
          <Navbar.Collapse id="psh-nav">
            <Nav className="me-auto">
              <Nav.Link as={Link} to="/services" className={isActive("/services") ? "nav-link active" : "nav-link"}>
                Services
              </Nav.Link>
              <Nav.Link
                as={Link}
                to="/services/new"
                className={isActive("/services/new") ? "nav-link active" : "nav-link"}
              >
                Create Service
              </Nav.Link>
              <Nav.Link as={Link} to="/tokens" className={isActive("/tokens") ? "nav-link active" : "nav-link"}>
                API Tokens
              </Nav.Link>
            </Nav>
            <Nav>
              <NavDropdown title={user?.username ?? "Account"} align="end">
                <NavDropdown.Item onClick={handleLogout}>Logout</NavDropdown.Item>
              </NavDropdown>
            </Nav>
          </Navbar.Collapse>
        </Container>
      </Navbar>
      <Container fluid="lg" className="py-4">
        {children}
      </Container>
    </>
  );
}
