import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

// Sizes and states follow docs/design/lingo-agent-design/component-spec.md §1: solid buttons
// darken by mixing in the foreground (12% hover, 22% pressed); outline / ghost use accent.
// Below md the default and icon sizes grow to 40px for touch.
const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md border border-transparent bg-clip-padding text-sm font-[550] whitespace-nowrap transition-colors outline-none select-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:pointer-events-none disabled:opacity-45 aria-invalid:border-destructive [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground hover:bg-[color-mix(in_oklab,var(--primary)_88%,var(--foreground))] active:bg-[color-mix(in_oklab,var(--primary)_78%,var(--foreground))]",
        outline:
          "border-input bg-card text-foreground hover:bg-accent active:bg-[color-mix(in_oklab,var(--accent)_80%,var(--foreground))] aria-expanded:bg-accent",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-[color-mix(in_oklab,var(--secondary)_92%,var(--foreground))] active:bg-[color-mix(in_oklab,var(--secondary)_84%,var(--foreground))] aria-expanded:bg-secondary",
        ghost:
          "text-foreground hover:bg-accent active:bg-[color-mix(in_oklab,var(--accent)_85%,var(--foreground))] aria-expanded:bg-accent",
        destructive:
          "bg-destructive/10 text-destructive hover:bg-destructive/17 active:bg-destructive/24",
        // Only for the final confirmation inside a dialog (component-spec §15).
        danger:
          "bg-destructive text-destructive-foreground hover:bg-[color-mix(in_oklab,var(--destructive)_88%,var(--foreground))] active:bg-[color-mix(in_oklab,var(--destructive)_78%,var(--foreground))]",
        link: "h-auto px-0.5 text-primary underline-offset-3 hover:underline",
      },
      size: {
        default: "h-10 px-3.5 md:h-9",
        xs: "h-6 gap-1 rounded-sm px-2 text-xs [&_svg:not([class*='size-'])]:size-3.5",
        sm: "h-8 px-2.5 text-[13px]",
        lg: "h-11 rounded-lg px-5 text-[15px]",
        icon: "size-10 md:size-9",
        "icon-xs": "size-6 rounded-sm [&_svg:not([class*='size-'])]:size-3.5",
        "icon-sm": "size-8",
        "icon-lg": "size-11 rounded-lg",
      },
    },
    compoundVariants: [{ variant: "link", className: "h-auto px-0.5" }],
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
