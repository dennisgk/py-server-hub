export type User = {
  id: number;
  username: string;
};

export type Service = {
  id: number;
  name: string;
  folder_name: string;
  archive_name: string;
  status: string;
  pid: number | null;
  created_at: string;
  updated_at: string;
};

export type UploadServiceResult = Service & {
  setup_logs: string[];
};

export type ServiceLogs = {
  stdout: string[];
  stderr: string[];
};

export type ApiToken = {
  id: number;
  name: string;
  token_prefix: string;
  created_at: string;
  last_used_at: string | null;
};

export type ApiTokenCreate = ApiToken & {
  token: string;
};
