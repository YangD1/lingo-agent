import { AuthForm } from "@/components/auth-form";

export default async function RegisterPage({ searchParams }: PageProps<"/register">) {
  const { next } = await searchParams;
  return <AuthForm mode="register" next={typeof next === "string" ? next : undefined} />;
}
