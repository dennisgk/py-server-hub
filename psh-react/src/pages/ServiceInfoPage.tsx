import { useCallback, useEffect, useState } from "react";
import { Alert, Badge, Button, ButtonGroup, Card, Col, Row, Spinner } from "react-bootstrap";
import { useNavigate, useParams } from "react-router-dom";
import { fetchService, fetchServiceLogs, removeService, startService, stopService } from "../api";
import type { Service, ServiceLogs } from "../types";

export function ServiceInfoPage() {
  const { serviceId } = useParams();
  const navigate = useNavigate();
  const serviceIdNumber = Number(serviceId);
  const [service, setService] = useState<Service | null>(null);
  const [logs, setLogs] = useState<ServiceLogs>({ stdout: [], stderr: [] });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(async () => {
    if (!serviceIdNumber) return;
    setLoading(true);
    setError(null);
    try {
      const [serviceData, logsData] = await Promise.all([
        fetchService(serviceIdNumber),
        fetchServiceLogs(serviceIdNumber),
      ]);
      setService(serviceData);
      setLogs(logsData);
    } catch {
      setError("Failed to load service info.");
    } finally {
      setLoading(false);
    }
  }, [serviceIdNumber]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  if (loading) {
    return <Spinner animation="border" />;
  }

  if (!service) {
    return <Alert variant="danger">Service not found.</Alert>;
  }

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-4">
        <h2 className="m-0">{service.name}</h2>
        <Badge bg={service.status === "running" ? "success" : "secondary"}>{service.status}</Badge>
      </div>
      {error && <Alert variant="danger">{error}</Alert>}
      <ButtonGroup className="mb-4">
        <Button
          variant="success"
          disabled={service.status === "running"}
          onClick={async () => {
            await startService(service.id);
            await loadData();
          }}
        >
          Start
        </Button>
        <Button
          variant="warning"
          disabled={service.status !== "running"}
          onClick={async () => {
            await stopService(service.id);
            await loadData();
          }}
        >
          Stop
        </Button>
        <Button
          variant="danger"
          onClick={async () => {
            if (!confirm(`Remove service "${service.name}" permanently?`)) {
              return;
            }
            await removeService(service.id);
            navigate("/services");
          }}
        >
          Remove
        </Button>
        <Button variant="secondary" onClick={() => void loadData()}>
          Refresh
        </Button>
      </ButtonGroup>
      <Row className="g-3">
        <Col lg={6}>
          <Card bg="dark" text="light">
            <Card.Header>Stdout</Card.Header>
            <Card.Body>
              <pre className="log-pane">{logs.stdout.join("\n") || "(no output yet)"}</pre>
            </Card.Body>
          </Card>
        </Col>
        <Col lg={6}>
          <Card bg="dark" text="light">
            <Card.Header>Stderr</Card.Header>
            <Card.Body>
              <pre className="log-pane">{logs.stderr.join("\n") || "(no errors yet)"}</pre>
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </>
  );
}
