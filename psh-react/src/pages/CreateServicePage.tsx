import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Card, Form } from "react-bootstrap";
import { useNavigate } from "react-router-dom";
import { fetchUploadJobStatus, getAuthToken, startUploadService } from "../api";

function guessName(filename: string): string {
  return filename.replace(/\.(zip|7z)$/i, "");
}

export function CreateServicePage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadLogs, setUploadLogs] = useState<string[]>([]);
  const [createdServiceId, setCreatedServiceId] = useState<number | null>(null);
  const streamRef = useRef<EventSource | null>(null);

  const namePlaceholder = useMemo(() => (file ? guessName(file.name) : ""), [file]);

  useEffect(
    () => () => {
      if (streamRef.current) {
        streamRef.current.close();
        streamRef.current = null;
      }
    },
    [],
  );

  const normalizeError = (detail: unknown): { message: string; setupLogs: string[] } => {
    if (typeof detail === "string") {
      return { message: detail, setupLogs: [] };
    }
    if (Array.isArray(detail)) {
      return { message: JSON.stringify(detail), setupLogs: [] };
    }
    if (detail && typeof detail === "object") {
      const detailObject = detail as { message?: string; setup_logs?: string[] };
      return {
        message: detailObject.message ?? JSON.stringify(detailObject),
        setupLogs: Array.isArray(detailObject.setup_logs) ? detailObject.setup_logs : [],
      };
    }
    return { message: "Upload failed.", setupLogs: [] };
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file) {
      setError("Please select a .zip or .7z file.");
      return;
    }
    setCreatedServiceId(null);
    setLoading(true);
    setError(null);
    if (streamRef.current) {
      streamRef.current.close();
      streamRef.current = null;
    }
    setUploadLogs([`Starting upload: ${file.name}`]);
    try {
      const uploadJob = await startUploadService(file, name || namePlaceholder);
      const token = getAuthToken();
      if (!token) {
        throw new Error("Missing auth token for streaming logs.");
      }
      setUploadLogs((previous) => [...previous, `Upload job started: ${uploadJob.job_id}`]);
      const streamUrl = `/api/services/upload-jobs/${uploadJob.job_id}/stream?token=${encodeURIComponent(token)}`;
      const stream = new EventSource(streamUrl);
      streamRef.current = stream;

      stream.onmessage = (streamEvent) => {
        try {
          const payload = JSON.parse(streamEvent.data) as {
            type: string;
            line?: string;
            status?: string;
            error_message?: string | null;
            service?: { id: number } | null;
          };
          if (payload.type === "log" && payload.line) {
            setUploadLogs((previous) => [...previous, payload.line ?? ""]);
            return;
          }
          if (payload.type === "done") {
            stream.close();
            streamRef.current = null;
            setLoading(false);
            if (payload.status === "completed" && payload.service?.id) {
              setCreatedServiceId(payload.service.id);
              setUploadLogs((previous) => [...previous, "Upload and setup completed."]);
            } else {
              setError(payload.error_message ?? "Upload failed.");
            }
          }
        } catch {
          setUploadLogs((previous) => [...previous, streamEvent.data]);
        }
      };

      stream.onerror = async () => {
        stream.close();
        streamRef.current = null;
        try {
          const status = await fetchUploadJobStatus(uploadJob.job_id);
          setUploadLogs(status.setup_logs);
          if (status.status === "completed" && status.service?.id) {
            setCreatedServiceId(status.service.id);
            setLoading(false);
            return;
          }
          if (status.status === "failed") {
            setError(status.error_message ?? "Upload failed.");
            setLoading(false);
            return;
          }
          setError("Log stream disconnected before upload finished.");
        } catch {
          setError("Log stream disconnected and upload status could not be retrieved.");
        } finally {
          setLoading(false);
        }
      };
    } catch (errorValue: unknown) {
      const detail = (errorValue as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      const normalized = normalizeError(detail);
      if (normalized.setupLogs.length > 0) {
        setUploadLogs(normalized.setupLogs);
      }
      setError(normalized.message);
      setLoading(false);
    }
  };

  return (
    <Card bg="dark" text="light">
      <Card.Body>
        <Card.Title className="mb-4">Create Service</Card.Title>
        {error && <Alert variant="danger">{error}</Alert>}
        <Form onSubmit={onSubmit}>
          <Form.Group className="mb-3">
            <Form.Label>Archive (.zip or .7z)</Form.Label>
            <Form.Control
              type="file"
              accept=".zip,.7z"
              onChange={(event) => {
                const selected = (event.target as HTMLInputElement).files?.[0] ?? null;
                setFile(selected);
                if (selected) {
                  setName(guessName(selected.name));
                }
              }}
              required
            />
          </Form.Group>
          <Form.Group className="mb-4">
            <Form.Label>Service Name</Form.Label>
            <Form.Control
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder={namePlaceholder || "my-service"}
            />
          </Form.Group>
          <Button type="submit" disabled={loading}>
            {loading ? "Uploading..." : "Upload Service"}
          </Button>
          {createdServiceId && (
            <Button
              type="button"
              variant="success"
              className="ms-2"
              onClick={() => navigate(`/services/${createdServiceId}`)}
            >
              Open Service
            </Button>
          )}
        </Form>
        {uploadLogs.length > 0 && (
          <>
            <hr />
            <Card.Subtitle className="mb-2">Setup Output</Card.Subtitle>
            <pre className="log-pane">{uploadLogs.join("\n")}</pre>
          </>
        )}
      </Card.Body>
    </Card>
  );
}
