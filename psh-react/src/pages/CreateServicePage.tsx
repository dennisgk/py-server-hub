import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Card, Form } from "react-bootstrap";
import { useNavigate } from "react-router-dom";
import { uploadService } from "../api";

function guessName(filename: string): string {
  return filename.replace(/\.(zip|7z)$/i, "");
}

export function CreateServicePage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const namePlaceholder = useMemo(() => (file ? guessName(file.name) : ""), [file]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file) {
      setError("Please select a .zip or .7z file.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const service = await uploadService(file, name || namePlaceholder);
      navigate(`/services/${service.id}`);
    } catch {
      setError("Upload failed. Ensure the archive root has requirements.txt and main.py.");
    } finally {
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
        </Form>
      </Card.Body>
    </Card>
  );
}
