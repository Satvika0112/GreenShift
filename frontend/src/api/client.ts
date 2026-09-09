import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

// Configurable API Base URL via Vite environment variable
const rawBaseUrl = import.meta.env.VITE_API_BASE_URL || '';
export const API_BASE_URL = rawBaseUrl.replace(/\/+$/, '');

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  },
});

// Request interceptor: inject real JWT Bearer token from sessionStorage
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = sessionStorage.getItem('greenshift_token');
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error: AxiosError) => Promise.reject(error)
);

// Response interceptor: structured error handling for 401, 403, 429, and network disconnects
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response) {
      const status = error.response.status;
      if (status === 401) {
        // Token expired or invalid: clear session
        sessionStorage.removeItem('greenshift_token');
        sessionStorage.removeItem('greenshift_user');
        window.dispatchEvent(new CustomEvent('greenshift:auth-expired'));
      } else if (status === 403) {
        console.warn('Access forbidden: insufficient permissions for resource');
      } else if (status === 429) {
        console.warn('Rate limit exceeded. Please wait a moment.');
      }
    } else if (error.request) {
      console.warn('Backend server unreachable at', API_BASE_URL || 'default proxy');
    }
    return Promise.reject(error);
  }
);

export default apiClient;
