/**
 * Basir DW-907: the UI hides admin-only entries only when the server says the user is an LS labeler.
 */
import { canManageProjects, getLsAccess } from "./ls-access";

const setLsAccess = (lsAccess?: object) => {
  (window as any).APP_SETTINGS = { user: lsAccess === undefined ? {} : { ls_access: lsAccess } };
};

describe("ls-access", () => {
  const original = (window as any).APP_SETTINGS;

  afterEach(() => {
    (window as any).APP_SETTINGS = original;
  });

  it("is upstream behaviour when the server sends nothing", () => {
    setLsAccess();
    expect(getLsAccess()).toBeNull();
    expect(canManageProjects()).toBe(true);
  });

  it("lets LS admins and everyone with access control off manage projects", () => {
    setLsAccess({ enabled: true, role: "admin", is_admin: true, can_manage: true, access_groups: [] });
    expect(canManageProjects()).toBe(true);
    setLsAccess({ enabled: false, role: null, is_admin: false, can_manage: true, access_groups: [] });
    expect(canManageProjects()).toBe(true);
  });

  it("hides admin-only entries for LS labelers", () => {
    setLsAccess({
      enabled: true,
      role: "labeler",
      is_admin: false,
      can_manage: false,
      access_groups: ["ls-sightence-male"],
    });
    expect(canManageProjects()).toBe(false);
    expect(getLsAccess()?.access_groups).toEqual(["ls-sightence-male"]);
  });
});
