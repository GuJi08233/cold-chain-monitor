export interface ApiResponse<T> {
  code: number;
  data: T;
  msg: string;
}

export interface PagedList<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type UserRole = "super_admin" | "admin" | "driver";

export interface LoginUser {
  user_id: number;
  username: string;
  role: UserRole;
  display_name?: string | null;
}

export interface LoginResult {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: LoginUser;
}

export interface AuthState {
  token: string;
  userId: number;
  username: string;
  displayName: string;
  role: UserRole;
}
