export async function callWorkspaceApi(params = {}) {
	const searchParams = new URLSearchParams(params);
	const response = await fetch(
		`/api/method/prastar_ai.api.opportunities.get_opportunity_workspace_data?${searchParams.toString()}`,
		{
			credentials: "same-origin",
			headers: {
				Accept: "application/json",
			},
		}
	);

	const payload = await response.json();

	if (!response.ok || payload.exc_type || payload.exception) {
		if (payload.exc_type === "PermissionError") {
			window.location.href = `/login?redirect-to=${encodeURIComponent(window.location.pathname)}`;
			throw new Error("Your session expired. Redirecting to login.");
		}

		throw new Error(payload.message || "Unable to load workspace data.");
	}

	return payload.message;
}
