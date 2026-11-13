// Wire shapes of auth-svc (auth-svc/docs/api/openapi.json). Exact field names, snake_case, readonly.

export interface UserDto {
  readonly id: string;
  readonly email: string;
  readonly full_name: string;
  readonly role: string;
  readonly last_login_at: string | null;
}

export interface TokenDto {
  readonly access_token: string;
  readonly token_type?: string;
  readonly expires_in: number;
  readonly user: UserDto;
}

export interface LoginRequestDto {
  readonly email: string;
  readonly password: string;
}

export interface SignupRequestDto extends LoginRequestDto {
  readonly full_name: string;
}

export interface ChangePasswordRequestDto {
  readonly current_password: string;
  readonly new_password: string;
}
