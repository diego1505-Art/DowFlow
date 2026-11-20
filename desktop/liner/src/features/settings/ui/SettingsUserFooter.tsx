import { UserAvatar } from "@/shared/ui";
import { useTranslation } from "@/languages";
import { useAuthStore } from "@/features/auth";
import { userDisplayName } from "@/entities/user";

export function SettingsUserFooter() {
  const { t } = useTranslation();
  const user = useAuthStore((state) => state.user);
  const displayName = userDisplayName(user) ?? "DowFlow Music";
  const handle = user?.username
    ? `@${user.username}`
    : (user?.email ?? t("settings.manage_account"));

  return (
    <div className="shrink-0 px-[10px] pt-[6px] pb-[10px]">
      <div className="flex min-w-0 items-center gap-[10px] rounded-item bg-fill p-[8px] pr-[6px]">
        <span className="relative shrink-0">
          <UserAvatar user={user ?? null} size={32} />
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-[2px] font-sans">
          <span className="truncate text-body leading-[16px] font-[500] text-text-primary">
            {displayName}
          </span>
          <span className="truncate text-caption leading-[15px] text-text-tertiary">
            {handle}
          </span>
        </span>
      </div>
    </div>
  );
}
