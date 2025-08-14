"""Large string constants used for SQL generation."""

import logging
import os

logger = logging.getLogger(__name__)
if os.getenv("DELINEA_DEBUG") and not logging.getLogger().handlers:
    logging.basicConfig(level=logging.DEBUG)  # pragma: no cover - config
logger.debug("constants module loaded")

TABLES_AND_COLUMNS = """
1. tbUser
   - UserId
   - Username
   - DisplayName
   - DomainId
   - LastLogin
   - Active
   - Enabled
   - EmailAddress
   - TwoFactor

2. tbDomain
   - DomainId
   - Domain

3. tbAuditUser
   - UserIdAffected
   - Action
   - Notes
   - DateRecorded
   - IpAddress
   - MachineName
   - DatabaseName
   - UserId

4. tbGroup
   - GroupID
   - GroupName
   - Active
   - IsPersonal
   - SystemGroup

5. tbSecret
   - SecretId
   - SecretName
   - FolderId
   - Created
   - Active
   - SecretTypeID
   - EnableInheritPermissions

6. tbFolder
   - FolderId
   - FolderPath
   - ParentFolderID
   - FolderName
   - EnableInheritPermissions

7. tbAuditSecret
   - SecretId
   - DateRecorded

8. tbSecretItem
   - SecretID
   - ItemValue
   - SecretFieldID

9. tbUserGroup
   - UserId
   - GroupId

10. tbRole
    - RoleID
    - Name
    - RoleType

11. tbRoleToGroup
    - RoleId
    - GroupId

12. tbRoleToRolePermission
    - RoleId
    - RolePermissionId

13. tbRolePermission
    - RolePermissionId
    - Name

14. vGroupSecretPermissions (view)
    - SecretId
    - GroupId
    - Permissions

15. vGroupFolderPermissions (view)
    - FolderId
    - GroupId
    - Permissions

16. vUserDisplayName (view)
    - UserId

17. vGroupDisplayName (view)
    - GroupId
    - DisplayName
"""

EXAMPLE_QUERIES_TEXT = """
1. Retrieve Secrets with Latest Audit Information:
   SELECT s.SecretID, s.SecretName, s.Created, s.Active, s.FolderID, s.SecretTypeID, a.latestdaterecorded
   FROM (SELECT audit.secretid, Max(audit.daterecorded) AS "latestdaterecorded"
         FROM tbauditsecret audit WITH (NOLOCK)
         GROUP BY audit.secretid) a
   INNER JOIN tbsecret s WITH (NOLOCK) ON s.secretid = a.secretid

2. Get Secret Inheritance Settings:
   SELECT s.SecretID, s.FolderID, s.EnableInheritPermissions FROM tbSecret s

3. Retrieve Folder Structure Information:
   SELECT f.folderID, f.ParentFolderID, f.FolderName, f.EnableInheritPermissions FROM tbFolder f

4. Get Group Permissions for Secrets:
   SELECT g.GroupId, s.SecretId, gsp.[Permissions]
   FROM tbSecret s WITH (NOLOCK)
   INNER JOIN vGroupSecretPermissions gsp ON s.SecretId = gsp.SecretId
   INNER JOIN tbGroup g WITH (NOLOCK) ON g.GroupId = gsp.GroupId

5. List All Groups:
   SELECT g.GroupID, g.GroupName FROM tbGroup g

6. List All Roles:
   SELECT r.RoleID, r.Name FROM tbRole r

7. Get Specific Secret Items:
   SELECT s.SecretID, si.[ItemValue], s.SecretName, si.SecretFieldID
   FROM tbSecret s
   LEFT JOIN tbSecretItem si on s.SecretID = si.SecretID
   WHERE si.SecretFieldID = 239 and SecretTypeId = 6035

8. Get User Permissions for Folders:
   SELECT u.UserId, f.FolderId, gfp.[Permissions]
   FROM tbFolder f WITH (NOLOCK)
   INNER JOIN vGroupFolderPermissions gfp ON f.FolderId = gfp.FolderId
   INNER JOIN tbUserGroup ug WITH (NOLOCK) ON gfp.GroupId = ug.GroupId
   INNER JOIN vUserDisplayName udn WITH (NOLOCK) ON udn.UserId = ug.UserId
   INNER JOIN tbUser u WITH (NOLOCK) ON u.UserId = ug.UserId
   INNER JOIN vGroupDisplayName gdn WITH (NOLOCK) ON gfp.GroupId = gdn.GroupId

9. Get User Role Permissions:
   SELECT u.UserID, rp.Name AS [Role Permission], r.RoleID AS [RoleID],
          g.IsPersonal AS [IsPersonal], g.GroupID as [vGroupDisplayName_DisplayName]
   FROM tbRoleToGroup rg WITH (NOLOCK)
   INNER JOIN tbRole r WITH (NOLOCK) ON rg.RoleId = r.RoleId AND r.RoleType = 1
   INNER JOIN tbRoleToRolePermission rtrp WITH (NOLOCK) ON r.RoleId = rtrp.RoleId
   INNER JOIN tbRolePermission rp WITH (NOLOCK) ON rp.RolePermissionId = rtrp.RolePermissionId
   INNER JOIN tbGroup g WITH (NOLOCK) ON rg.GroupId = g.GroupId
   INNER JOIN tbUserGroup ug WITH (NOLOCK) ON g.GroupId = ug.GroupId
   INNER JOIN tbUser u WITH (NOLOCK) ON ug.UserId = u.UserId
   INNER JOIN vGroupDisplayName WITH (NOLOCK) ON g.GroupID = vGroupDisplayName.GroupId

10. List Users with Basic Information:
    SELECT u.UserID, u.UserName, u.DisplayName, u.LastLogin, u.Enabled, u.EmailAddress, u.TwoFactor
    FROM tbUser u
"""

SPECIAL_FIELDS = """
## Primary Parameters
1. `#STARTDATE`: Calendar picker for start date
2. `#ENDDATE`: Calendar picker for end date
3. `#USER`: Dropdown list of active users
4. `#ORGANIZATION`: Returns current instance's organization code (for Secret Server Online only)
5. `#GROUP`: Dropdown list of active groups
6. `#FOLDERID`: Folder picker that returns a folder ID
7. `#FOLDERPATH`: Folder picker that returns the folder path
8. `#CUSTOMTEXT`: Free text input for searching

## Additional Parameters
9. `#ENDCURRENTMONTH`: Last day of current month
10. `#ENDCURRENTYEAR`: December 31st of current year
11. `#ENDPREVIOUSMONTH`: Last day of previous month at 11:59:59 PM
12. `#ENDPREVIOUSYEAR`: December 31st of previous year
13. `#ENDTODAY`: End of today at 11:59:59 PM
14. `#ENDWEEK`: End of current week (Sunday) at 11:59:59 PM
15. `#ENDYESTERDAY`: End of yesterday at 11:59:59 PM
16. `#STARTCURRENTMONTH`: First day of current month
17. `#STARTCURRENTYEAR`: January 1st of current year
18. `#STARTPREVIOUSMONTH`: First day of previous month at 12:00 AM
19. `#STARTPREVIOUSYEAR`: January 1st of previous year
20. `#STARTTODAY`: Beginning of today at 12:00 AM
21. `#STARTWEEK`: Beginning of current week (Monday) at 12:00 AM
22. `#STARTYESTERDAY`: Beginning of yesterday at 12:00 AM

## Special Column
- `Color`: When included in a SQL query, this column will apply the specified color to the row in the report.
"""
