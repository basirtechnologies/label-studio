/**
 * Basir DW-907: the user's LS role, as the server put it on the page (window.APP_SETTINGS.user.ls_access).
 * The UI only hides admin-only entries for labelers; the server enforces the rules either way.
 */
export type LsAccess = {
  enabled: boolean;
  role: "admin" | "labeler" | null;
  is_admin: boolean;
  /** true for LS admins, and for everyone while access control is off */
  can_manage: boolean;
  access_groups: string[];
};

export const getLsAccess = (): LsAccess | null => (window as any).APP_SETTINGS?.user?.ls_access ?? null;

/** Create/configure projects, import, export, organization pages. True unless the server says otherwise. */
export const canManageProjects = (): boolean => getLsAccess()?.can_manage !== false;
