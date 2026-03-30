import axios from "axios";
import type { ApiToken, ApiTokenCreate, Service, ServiceLogs, User } from "./types";

const API_BASE = "/api";

let jwtToken: string | null = null;

export function setAuthToken(token: string | null) {
  jwtToken = token;
}

const client = axios.create({
  baseURL: API_BASE,
});

client.interceptors.request.use((config) => {
  if (jwtToken) {
    config.headers.Authorization = `Bearer ${jwtToken}`;
  }
  return config;
});

export async function login(username: string, password: string): Promise<string> {
  const response = await client.post<{ access_token: string }>("/auth/login", { username, password });
  return response.data.access_token;
}

export async function logout(): Promise<void> {
  await client.post("/auth/logout");
}

export async function fetchMe(): Promise<User> {
  const response = await client.get<User>("/auth/me");
  return response.data;
}

export async function fetchServices(): Promise<Service[]> {
  const response = await client.get<Service[]>("/services");
  return response.data;
}

export async function fetchService(serviceId: number): Promise<Service> {
  const response = await client.get<Service>(`/services/${serviceId}`);
  return response.data;
}

export async function fetchServiceLogs(serviceId: number): Promise<ServiceLogs> {
  const response = await client.get<ServiceLogs>(`/services/${serviceId}/logs`);
  return response.data;
}

export async function startService(serviceId: number): Promise<Service> {
  const response = await client.post<Service>(`/services/${serviceId}/start`);
  return response.data;
}

export async function stopService(serviceId: number): Promise<void> {
  await client.post(`/services/${serviceId}/stop`);
}

export async function removeService(serviceId: number): Promise<void> {
  await client.delete(`/services/${serviceId}`);
}

export async function uploadService(file: File, name?: string): Promise<Service> {
  const formData = new FormData();
  formData.append("file", file);
  if (name) {
    formData.append("name", name);
  }
  const response = await client.post<Service>("/services/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return response.data;
}

export async function fetchTokens(): Promise<ApiToken[]> {
  const response = await client.get<ApiToken[]>("/tokens");
  return response.data;
}

export async function createToken(name: string): Promise<ApiTokenCreate> {
  const response = await client.post<ApiTokenCreate>("/tokens", { name });
  return response.data;
}

export async function deleteToken(id: number): Promise<void> {
  await client.delete(`/tokens/${id}`);
}
