"use client";

interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  children: React.ReactNode;
  variant?: "primary" | "secondary" | "ghost";
  size?: "sm" | "md" | "lg";
}

export function IconButton({
  children,
  variant = "secondary",
  size = "md",
  className = "",
  ...props
}: IconButtonProps) {
  const baseStyles =
    "rounded-lg transition-colors duration-200 flex items-center justify-center";

  const variantStyles = {
    primary: "bg-blue-500 text-white hover:bg-blue-600 active:bg-blue-700",
    secondary: "bg-gray-700 text-gray-100 hover:bg-gray-600 active:bg-gray-500",
    ghost:
      "text-gray-400 hover:text-gray-200 hover:bg-gray-700/50 active:bg-gray-600/50",
  };

  const sizeStyles = {
    sm: "p-2 text-sm",
    md: "p-2.5 text-base",
    lg: "p-3 text-lg",
  };

  return (
    <button
      className={`${baseStyles} ${variantStyles[variant]} ${sizeStyles[size]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}
