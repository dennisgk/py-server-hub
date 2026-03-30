import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Col, Dropdown, Row, Spinner } from "react-bootstrap";
import { Link, useNavigate } from "react-router-dom";
import { fetchServices, removeService, startService, stopService } from "../api";
import type { Service } from "../types";

export function ServiceViewPage() {
  const navigate = useNavigate();
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadServices = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchServices();
      setServices(data);
    } catch {
      setError("Failed to load services.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadServices();
  }, []);

  const withRefresh = async (handler: () => Promise<void>) => {
    try {
      await handler();
      await loadServices();
    } catch {
      setError("Action failed.");
    }
  };

  if (loading) {
    return <Spinner animation="border" />;
  }

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-4">
        <h2 className="m-0">Services</h2>
        <Button variant="primary" onClick={() => navigate("/services/new")}>
          Create Service
        </Button>
      </div>
      {error && <Alert variant="danger">{error}</Alert>}
      <Row xs={1} md={2} lg={3} className="g-3">
        {services.map((service) => (
          <Col key={service.id}>
            <Card bg="dark" text="light" className="h-100">
              <Card.Body>
                <div className="d-flex justify-content-between align-items-start mb-2">
                  <Card.Title className="m-0">{service.name}</Card.Title>
                  <Dropdown align="end">
                    <Dropdown.Toggle variant="secondary" size="sm" id={`service-menu-${service.id}`}>
                      ⋯
                    </Dropdown.Toggle>
                    <Dropdown.Menu>
                      <Dropdown.Item as={Link} to={`/services/${service.id}`}>
                        Open Service
                      </Dropdown.Item>
                      <Dropdown.Item
                        onClick={() =>
                          void withRefresh(() => (service.status === "running" ? stopService(service.id) : startService(service.id).then(() => undefined)))
                        }
                      >
                        {service.status === "running" ? "Stop" : "Start"}
                      </Dropdown.Item>
                      <Dropdown.Item
                        className="text-danger"
                        onClick={() => {
                          if (confirm(`Remove service "${service.name}"?`)) {
                            void withRefresh(() => removeService(service.id));
                          }
                        }}
                      >
                        Remove
                      </Dropdown.Item>
                    </Dropdown.Menu>
                  </Dropdown>
                </div>
                <Card.Text className="mb-2">
                  <small>Archive: {service.archive_name}</small>
                </Card.Text>
                <Badge bg={service.status === "running" ? "success" : "secondary"}>{service.status}</Badge>
              </Card.Body>
            </Card>
          </Col>
        ))}
      </Row>
      {services.length === 0 && <Alert variant="secondary">No services yet. Upload one to begin.</Alert>}
    </>
  );
}
