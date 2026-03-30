import { useEffect, useState } from "react";
import { Alert, Button, Card, Form, InputGroup, Table } from "react-bootstrap";
import { createToken, deleteToken, fetchTokens } from "../api";
import type { ApiToken } from "../types";

export function ApiTokensPage() {
  const [tokens, setTokens] = useState<ApiToken[]>([]);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [newToken, setNewToken] = useState<string | null>(null);

  const loadTokens = async () => {
    setError(null);
    try {
      setTokens(await fetchTokens());
    } catch {
      setError("Failed to load API tokens.");
    }
  };

  useEffect(() => {
    void loadTokens();
  }, []);

  return (
    <Card bg="dark" text="light">
      <Card.Body>
        <Card.Title className="mb-4">API Tokens</Card.Title>
        {error && <Alert variant="danger">{error}</Alert>}
        {newToken && (
          <Alert variant="warning">
            Copy this token now. It is only shown once:
            <hr />
            <code>{newToken}</code>
          </Alert>
        )}
        <Form
          className="mb-4"
          onSubmit={async (event) => {
            event.preventDefault();
            if (!name.trim()) return;
            const created = await createToken(name.trim());
            setNewToken(created.token);
            setName("");
            await loadTokens();
          }}
        >
          <InputGroup>
            <Form.Control
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Token name (e.g. CI Runner)"
              required
            />
            <Button type="submit">Create Token</Button>
          </InputGroup>
        </Form>
        <Table striped bordered hover variant="dark" responsive>
          <thead>
            <tr>
              <th>Name</th>
              <th>Prefix</th>
              <th>Created</th>
              <th>Last Used</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {tokens.map((token) => (
              <tr key={token.id}>
                <td>{token.name}</td>
                <td>{token.token_prefix}</td>
                <td>{new Date(token.created_at).toLocaleString()}</td>
                <td>{token.last_used_at ? new Date(token.last_used_at).toLocaleString() : "-"}</td>
                <td className="text-end">
                  <Button
                    variant="outline-danger"
                    size="sm"
                    onClick={async () => {
                      await deleteToken(token.id);
                      await loadTokens();
                    }}
                  >
                    Delete
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card.Body>
    </Card>
  );
}
