import { useCallback, useEffect, useState } from "react";
import { Button, Typography, useToast } from "@humansignal/ui";
import Input from "../../components/Form/Elements/Input/Input";
import { useAPI } from "../../providers/ApiProvider";

const GROUP_NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

/**
 * Basir DW-907: the access groups of a project (LS admins only). Labelers only see projects sharing a group
 * with them while access control is on.
 */
export const AccessGroupsSettings = ({ project }) => {
  const api = useAPI();
  const toast = useToast();
  const [groups, setGroups] = useState(null);
  const [saved, setSaved] = useState([]);
  const [known, setKnown] = useState([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!project?.id) return;
    let cancelled = false;
    api
      .callApi("project", { params: { pk: project.id, include: "access_groups" }, errorFilter: () => true })
      .then((data) => {
        if (cancelled || !data || data.error) return;
        setGroups(data.access_groups ?? []);
        setSaved(data.access_groups ?? []);
      });
    // the group list is for LS admins only; without it there are just no suggestions
    api.callApi("accessGroups", { errorFilter: () => true }).then((data) => {
      if (!cancelled && Array.isArray(data)) setKnown(data.map((group) => group.name));
    });
    return () => {
      cancelled = true;
    };
  }, [project?.id]);

  const addGroup = useCallback(() => {
    const name = draft.trim();
    if (!name) return;
    if (!GROUP_NAME.test(name)) {
      setError('Use letters, digits, "-", "_" and "." only, e.g. ls-sightence-male');
      return;
    }
    setError(null);
    setGroups((current) => (current.includes(name) ? current : [...current, name]));
    setDraft("");
  }, [draft]);

  const save = useCallback(async () => {
    setSaving(true);
    const response = await api.callApi("updateProject", {
      params: { pk: project.id },
      body: { access_groups: groups },
      errorFilter: () => true,
    });
    setSaving(false);
    if (response?.access_groups) {
      setGroups(response.access_groups);
      setSaved(response.access_groups);
      toast?.show({ message: "Access groups saved" });
    } else {
      setError(response?.response?.detail ?? "Could not save the access groups");
    }
  }, [groups, project?.id]);

  if (groups === null) return null;

  const changed = groups.join(",") !== saved.join(",");

  return (
    <div className="mt-wider flex flex-col gap-tight" data-testid="access-groups-settings">
      <Typography variant="headline" size="small">
        Access groups
      </Typography>
      <Typography size="small" className="text-neutral-content-subtler">
        LS labelers only see this project if they are in one of its groups. LS admins see every project.
      </Typography>
      <div className="flex flex-wrap gap-tight">
        {groups.length === 0 && (
          <Typography size="small" className="text-neutral-content-subtler">
            No groups: only LS admins can see this project.
          </Typography>
        )}
        {groups.map((group) => (
          <span
            key={group}
            className="inline-flex items-center gap-tightest rounded-smallest border border-neutral-border px-tight py-tightest text-body-small"
          >
            {group}
            <button
              type="button"
              aria-label={`Remove ${group}`}
              className="text-neutral-content-subtler hover:text-negative-content"
              onClick={() => setGroups((current) => current.filter((name) => name !== group))}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="flex items-start gap-tight">
        <Input
          name="access-group"
          placeholder="Add a group, e.g. ls-sightence-male"
          value={draft}
          list="access-group-names"
          autoComplete="off"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              addGroup();
            }
          }}
        />
        <datalist id="access-group-names">
          {known
            .filter((name) => !groups.includes(name))
            .map((name) => (
              <option key={name} value={name} />
            ))}
        </datalist>
        <Button look="outlined" onClick={addGroup} aria-label="Add access group">
          Add
        </Button>
      </div>
      {error && (
        <Typography size="small" className="text-negative-content">
          {error}
        </Typography>
      )}
      <div>
        <Button onClick={save} disabled={!changed || saving} waiting={saving} aria-label="Save access groups">
          Save access groups
        </Button>
      </div>
    </div>
  );
};
