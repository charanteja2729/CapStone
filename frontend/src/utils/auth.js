// simple utils for token + headers
const TOKEN_KEY = 'access_token';

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch (e) {
    console.warn('getToken error', e);
    return null;
  }
}

// isJson -> include Content-Type: application/json
export function getAuthHeaders(isJson = false) {
  const headers = {};
  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  if (isJson) {
    headers['Content-Type'] = 'application/json';
  }
  return headers;
}

export function removeToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch (e) {
    console.warn('removeToken error', e);
  }
}
